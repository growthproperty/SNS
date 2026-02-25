#!/usr/bin/env python3
"""
LINE Bot サーバー

LINEのトークにURLを送るだけで：
  1. 投稿を取得・保存
  2. 引用コメント5案を即返信

コマンド一覧:
  <URL>            → 投稿を保存して引用コメントを生成
  original         → 蓄積コンテキストからオリジナルポストを生成
  list             → 最近の投稿5件を表示
  show <ID>        → 投稿の詳細とコメントを表示
  generate <ID>    → 指定IDの引用コメントを再生成
  help             → 使い方を表示

起動:
  gunicorn server.app:app  (本番)
  python server/app.py     (ローカル確認)

環境変数:
  LINE_CHANNEL_SECRET          LINEチャンネルシークレット
  LINE_CHANNEL_ACCESS_TOKEN    LINEチャンネルアクセストークン
  PORT                         ポート番号（デフォルト: 8000）
"""

import os
import re
import sys
import threading

from flask import Flask, request, abort

# プロジェクトルートを sys.path に追加（server/ ディレクトリから実行された場合も対応）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from database.db import (
    get_all_posts,
    get_comments_for_post,
    get_post_by_id,
    get_posts_for_context,
    init_db,
    save_comments,
    save_post,
    update_post_insights,
)

# ── 初期化 ────────────────────────────────────────────────────────

app = Flask(__name__)
init_db()

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    print(
        "[WARNING] LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN が未設定です。"
        ".env ファイルを確認してください。"
    )

handler = WebhookHandler(LINE_CHANNEL_SECRET)
_line_config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# ── ルーティング ──────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    """ヘルスチェック / デプロイ確認用"""
    from database.db import get_all_posts as _get
    count = len(_get(limit=9999))
    return f"SNS Bot is running. 収集済み投稿: {count}件", 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK", 200


# ── メッセージハンドラー ───────────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def on_message(event: MessageEvent):
    text = event.message.text.strip()
    reply_token = event.reply_token
    destination = _get_destination(event)

    # URL が送られてきた場合
    if re.match(r"https?://\S+", text):
        _reply(reply_token, ["🔍 コンテンツを取得中です...\n引用コメント生成まで15〜30秒かかります。少々お待ちください。"])
        if destination:
            threading.Thread(
                target=_process_url_async,
                args=(text.split()[0], destination),  # 複数URL対応: 先頭URLを処理
                daemon=True,
            ).start()
        return

    cmd = text.lower()

    # original / オリジナル
    if cmd in ("original", "オリジナル", "orig"):
        posts = get_posts_for_context(limit=30)
        if not posts:
            _reply(reply_token, ["投稿がまだありません。まずURLを送信して投稿を蓄積してください。"])
            return
        _reply(reply_token, [f"⚡ {len(posts)}件のコンテキストからオリジナルポストを生成中...\n20〜40秒かかります。"])
        if destination:
            threading.Thread(
                target=_generate_original_async,
                args=(destination,),
                daemon=True,
            ).start()
        return

    # list / 一覧
    if cmd in ("list", "一覧", "リスト", "ls"):
        posts = get_all_posts(limit=7)
        if not posts:
            _reply(reply_token, ["投稿がまだありません。URLを送信して追加してください。"])
            return
        lines = [f"📋 最近の投稿（{len(posts)}件）\n"]
        for p in posts:
            mark = "✅" if p["generated_at"] else "▪"
            preview = (p["content"] or "")[:40].replace("\n", " ")
            source_icon = {"x": "𝕏", "note": "📝", "web": "🌐"}.get(p["source"], "📄")
            lines.append(f"{mark} ID:{p['id']} {source_icon} {preview}...")
        lines.append("\n詳細は「show <ID>」で確認できます")
        _reply(reply_token, ["\n".join(lines)])
        return

    # show <ID>
    if cmd.startswith("show "):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            _send_post_detail(reply_token, int(parts[1]))
        else:
            _reply(reply_token, ["使い方: show <ID>\n例: show 3"])
        return

    # generate <ID>
    if cmd.startswith("generate ") or cmd.startswith("gen "):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            post_id = int(parts[1])
            post = get_post_by_id(post_id)
            if not post:
                _reply(reply_token, [f"ID:{post_id} の投稿が見つかりません。\n「list」で投稿一覧を確認してください。"])
                return
            _reply(reply_token, [f"🔄 ID:{post_id} の引用コメントを再生成中..."])
            if destination:
                threading.Thread(
                    target=_generate_comments_async,
                    args=(post_id, destination),
                    daemon=True,
                ).start()
        else:
            _reply(reply_token, ["使い方: generate <ID>\n例: generate 3"])
        return

    # help / ヘルプ
    if cmd in ("help", "ヘルプ", "使い方", "?", "？"):
        _reply(reply_token, [_help_text()])
        return

    # 不明なメッセージ
    _reply(reply_token, [
        "URLを送信すると引用コメントを自動生成します 📲\n\n"
        "「help」と送ると使い方を確認できます"
    ])


# ── 非同期処理（スレッド） ────────────────────────────────────────

def _process_url_async(url: str, destination: str):
    """URL取得・保存・コメント生成をバックグラウンドで実行してプッシュ通知する"""
    try:
        from collectors.url_fetcher import fetch_from_url
        result = fetch_from_url(url)
    except RuntimeError as e:
        _push(destination, [f"❌ 取得エラー\n\n{e}\n\nX投稿の場合はX APIキーの設定が必要な場合があります。"])
        return

    # DB保存
    post_db_id = save_post(
        source=result.source,
        post_id=result.post_id,
        author=result.author,
        content=result.content,
        url=result.url,
        like_count=result.like_count,
        quote_count=result.quote_count,
        reply_count=result.reply_count,
        retweet_count=result.retweet_count,
    )

    is_duplicate = post_db_id is None
    if is_duplicate:
        # 既存投稿のIDを取得
        from database.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM posts WHERE post_id = ?", (result.post_id,)
            ).fetchone()
            post_db_id = row["id"] if row else None

    if not post_db_id:
        _push(destination, ["❌ 保存に失敗しました。"])
        return

    # 保存完了通知
    source_icon = {"x": "𝕏", "note": "📝", "web": "🌐"}.get(result.source, "📄")
    status = "既存の投稿" if is_duplicate else "保存完了"
    preview = (result.content or "")[:120]
    saved_msg = (
        f"{source_icon} {status}（ID:{post_db_id}）\n\n"
        f"👤 {result.author or '不明'}\n"
        f"{preview}{'...' if len(result.content or '') > 120 else ''}"
    )
    _push(destination, [saved_msg])

    # 洞察の抽出（Haiku - 高速・低コスト）
    try:
        from generator.original_post_generator import OriginalPostGenerator
        insights = OriginalPostGenerator().extract_insights([{
            "source": result.source,
            "author": result.author,
            "content": result.content,
        }])
        update_post_insights(post_db_id, insights)
    except Exception:
        pass  # 洞察抽出失敗はサイレントに無視

    # 引用コメント生成（Opus - 高品質）
    try:
        from generator.comment_generator import CommentGenerator
        comments = CommentGenerator().generate(
            author=result.author or "",
            content=result.content or "",
            url=result.url or "",
        )
    except Exception as e:
        _push(destination, [f"❌ コメント生成エラー: {e}"])
        return

    save_comments(post_db_id, comments)

    # コメントを送信（1メッセージにまとめる）
    labels = ["共感・補足型", "問いかけ型", "具体化型", "反骨・逆説型", "行動促進型"]
    lines = ["💬 引用コメント5案\n"]
    for i, (comment, label) in enumerate(zip(comments, labels), start=1):
        lines.append(f"【案{i} {label}】\n{comment}")
    _push(destination, ["\n\n".join(lines)])


def _generate_original_async(destination: str):
    """オリジナルポスト生成をバックグラウンドで実行してプッシュ通知する"""
    posts = get_posts_for_context(limit=30)
    try:
        from generator.original_post_generator import OriginalPostGenerator
        results = OriginalPostGenerator().generate(posts)
    except Exception as e:
        _push(destination, [f"❌ オリジナルポスト生成エラー: {e}"])
        return

    from database.db import save_original_posts
    save_original_posts(results)

    type_labels = ["真実型", "対比型", "数字型", "問い型", "法則型"]
    lines = ["🔥 オリジナルポスト5案\n"]
    for i, post in enumerate(results):
        label = type_labels[i] if i < len(type_labels) else f"案{i+1}"
        theme = post.get("theme", "")
        theme_str = f"（{theme}）" if theme else ""
        lines.append(f"【{label}{theme_str}】\n{post.get('content', '')}")
    _push(destination, ["\n\n".join(lines)])


def _generate_comments_async(post_id: int, destination: str):
    """引用コメント再生成をバックグラウンドで実行してプッシュ通知する"""
    post = get_post_by_id(post_id)
    if not post:
        _push(destination, [f"ID:{post_id} の投稿が見つかりません。"])
        return
    try:
        from generator.comment_generator import CommentGenerator
        comments = CommentGenerator().generate(
            author=post["author"] or "",
            content=post["content"] or "",
            url=post["url"] or "",
        )
    except Exception as e:
        _push(destination, [f"❌ 生成エラー: {e}"])
        return

    save_comments(post_id, comments)

    labels = ["共感・補足型", "問いかけ型", "具体化型", "反骨・逆説型", "行動促進型"]
    lines = [f"💬 ID:{post_id} 引用コメント5案（再生成）\n"]
    for i, (comment, label) in enumerate(zip(comments, labels), start=1):
        lines.append(f"【案{i} {label}】\n{comment}")
    _push(destination, ["\n\n".join(lines)])


# ── ユーティリティ ────────────────────────────────────────────────

def _send_post_detail(reply_token: str, post_id: int):
    post = get_post_by_id(post_id)
    if not post:
        _reply(reply_token, [f"ID:{post_id} の投稿が見つかりません。"])
        return

    source_icon = {"x": "𝕏", "note": "📝", "web": "🌐"}.get(post["source"], "📄")
    detail = (
        f"{source_icon} 投稿 ID:{post_id}\n\n"
        f"👤 {post['author'] or '不明'}\n"
        f"{(post['content'] or '')[:200]}{'...' if len(post['content'] or '') > 200 else ''}\n\n"
        f"❤️ いいね: {post['like_count']:,}  🔁 引用: {post['quote_count']}\n"
        f"🔗 {post['url']}"
    )

    comments = get_comments_for_post(post_id)
    if not comments:
        _reply(reply_token, [detail, f"コメントはまだ生成されていません。\n「generate {post_id}」で生成できます。"])
        return

    labels = ["共感・補足型", "問いかけ型", "具体化型", "反骨・逆説型", "行動促進型"]
    lines = [f"💬 引用コメント5案\n"]
    for c in comments:
        i = c["comment_number"]
        label = labels[i - 1] if i - 1 < len(labels) else f"案{i}"
        lines.append(f"【案{i} {label}】\n{c['comment']}")
    _reply(reply_token, [detail, "\n\n".join(lines)])


def _help_text() -> str:
    return (
        "📖 SNS Bot 使い方\n\n"
        "【基本】\n"
        "URLを送信\n"
        "→ 投稿を保存して引用コメント5案を生成\n\n"
        "【コマンド】\n"
        "list\n"
        "→ 最近の投稿を一覧表示\n\n"
        "show <ID>\n"
        "→ 投稿の詳細とコメントを表示\n\n"
        "generate <ID>\n"
        "→ 引用コメントを再生成\n\n"
        "original\n"
        "→ 蓄積したコンテキストから\n"
        "　 オリジナルポストを生成\n\n"
        "help\n"
        "→ この使い方を表示"
    )


def _get_destination(event: MessageEvent) -> str | None:
    """返信先のIDを取得する（グループ優先）"""
    source = event.source
    if hasattr(source, "group_id") and source.group_id:
        return source.group_id
    if hasattr(source, "room_id") and source.room_id:
        return source.room_id
    if hasattr(source, "user_id") and source.user_id:
        return source.user_id
    return None


def _reply(reply_token: str, messages: list[str]):
    """replyTokenを使って即時返信する（1回限り、15秒以内）"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        with ApiClient(_line_config) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=m[:4999]) for m in messages[:5]],
                )
            )
    except Exception as e:
        print(f"[LINE reply error] {e}")


def _push(destination: str, messages: list[str]):
    """push APIで任意のタイミングにメッセージを送る（バックグラウンド処理後の通知用）"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not destination:
        return
    try:
        with ApiClient(_line_config) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(
                    to=destination,
                    messages=[TextMessage(text=m[:4999]) for m in messages[:5]],
                )
            )
    except Exception as e:
        print(f"[LINE push error] {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting SNS Bot server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
