#!/usr/bin/env python3
"""
バズ投稿収集 & 引用コメント生成ツール

使い方:
  python main.py add <URL>         -- URLから投稿を取得・保存し、引用コメントを即生成
  python main.py collect           -- XとnoteからBuzz投稿を自動収集
  python main.py collect --source x    -- Xのみ収集
  python main.py collect --source note -- noteのみ収集
  python main.py list              -- 収集済み投稿を一覧表示
  python main.py show <ID>         -- 投稿の詳細と生成済みコメントを表示
  python main.py generate <ID>     -- 指定投稿の引用コメント5案を再生成
  python main.py original          -- 蓄積コンテキストからオリジナルポストを生成
  python main.py original --show   -- 前回生成したオリジナルポストを再表示
"""

import sys
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from database.db import (
    init_db,
    get_all_posts,
    get_post_by_id,
    save_comments,
    get_comments_for_post,
    get_posts_for_context,
    save_original_posts,
    get_original_posts,
    update_post_insights,
    save_post,
)

console = Console()


@click.group()
def cli():
    """バズ投稿収集 & 引用コメント生成ツール"""
    init_db()


# ── add ──────────────────────────────────────────────────────────

@cli.command()
@click.argument("url")
@click.option(
    "--no-generate",
    is_flag=True,
    default=False,
    help="引用コメントの自動生成をスキップする",
)
def add(url: str, no_generate: bool):
    """URLを指定して投稿を取得・保存し、引用コメントを即座に生成する"""

    # 1. URLからコンテンツ取得
    console.print(f"[cyan]コンテンツを取得中: {url}[/cyan]")
    try:
        from collectors.url_fetcher import fetch_from_url
        result = fetch_from_url(url)
    except RuntimeError as e:
        console.print(f"[red]取得エラー: {e}[/red]")
        sys.exit(1)

    # 2. DBに保存
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

    if post_db_id is None:
        # 既存の投稿: IDを取得して続行
        with __import__("database.db", fromlist=["get_connection"]).get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM posts WHERE url = ? OR post_id = ?",
                (result.url, result.post_id),
            ).fetchone()
            post_db_id = row["id"] if row else None

        if post_db_id:
            console.print(
                f"[yellow]この投稿はすでに保存済みです（ID:{post_db_id}）。"
                f"コメント生成を続行します。[/yellow]"
            )
        else:
            console.print("[red]保存に失敗しました。[/red]")
            sys.exit(1)
    else:
        console.print(f"[green]保存完了！（ID:{post_db_id}）[/green]")

    # 3. 投稿内容を表示
    source_badge = {
        "x": "[blue]X[/blue]",
        "note": "[green]note[/green]",
        "web": "[magenta]web[/magenta]",
    }.get(result.source, result.source)

    console.print(
        Panel(
            f"[bold]{result.content[:300]}{'...' if len(result.content) > 300 else ''}[/bold]\n\n"
            f"[dim]著者: {result.author or '不明'}[/dim]\n"
            f"[dim]URL: {result.url}[/dim]",
            title=f"{source_badge} 投稿 ID:{post_db_id}",
            border_style="cyan",
        )
    )

    # 4. 洞察の抽出（バックグラウンド的に）
    try:
        from generator.original_post_generator import OriginalPostGenerator
        gen = OriginalPostGenerator()
        insights_json = gen.extract_insights([{
            "source": result.source,
            "author": result.author,
            "content": result.content,
        }])
        update_post_insights(post_db_id, insights_json)
        console.print("[dim]洞察を抽出してコンテキストに保存しました[/dim]")
    except Exception:
        pass  # 洞察抽出は失敗してもフローを止めない

    # 5. 引用コメント生成
    if no_generate:
        console.print(
            f"\n[dim]引用コメントをスキップしました。"
            f"`python main.py generate {post_db_id}` で後から生成できます。[/dim]"
        )
        return

    _run_generate(post_db_id, result.content, result.author, result.url)


# ── collect ───────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--source",
    type=click.Choice(["x", "note", "all"]),
    default="all",
    show_default=True,
    help="収集元のプラットフォーム",
)
@click.option(
    "--pages",
    default=3,
    show_default=True,
    help="note収集時のページ数（1ページ約20件）",
)
def collect(source: str, pages: int):
    """XとnoteからBuzz投稿を自動収集してDBに保存する"""

    if source in ("x", "all"):
        console.print("[bold cyan]X (Twitter) からバズ投稿を収集中...[/bold cyan]")
        try:
            from collectors.x_collector import XCollector
            saved, skipped = XCollector().collect()
            console.print(
                f"  [green]X: 新規保存 {saved}件 / スキップ（重複）{skipped}件[/green]"
            )
        except ValueError as e:
            console.print(f"  [red]X 収集スキップ: {e}[/red]")
        except Exception as e:
            console.print(f"  [red]X 収集エラー: {e}[/red]")

    if source in ("note", "all"):
        console.print("[bold cyan]note.com からビジネス記事を収集中...[/bold cyan]")
        try:
            from collectors.note_collector import NoteCollector
            saved, skipped = NoteCollector().collect(pages=pages)
            console.print(
                f"  [green]note: 新規保存 {saved}件 / スキップ（重複）{skipped}件[/green]"
            )
        except Exception as e:
            console.print(f"  [red]note 収集エラー: {e}[/red]")

    console.print("\n[bold]収集完了。[/bold] `python main.py list` で一覧を確認できます。")


# ── list ─────────────────────────────────────────────────────────

@cli.command("list")
@click.option(
    "--source",
    type=click.Choice(["x", "note", "web", "all"]),
    default="all",
    show_default=True,
    help="表示するプラットフォーム",
)
@click.option(
    "--limit",
    default=30,
    show_default=True,
    help="表示件数",
)
def list_posts(source: str, limit: int):
    """収集済み投稿を一覧表示する"""
    src = None if source == "all" else source
    posts = get_all_posts(source=src, limit=limit)

    if not posts:
        console.print(
            "[yellow]投稿が見つかりません。"
            "`add <URL>` または `collect` で投稿を追加してください。[/yellow]"
        )
        return

    source_colors = {"x": "[blue]X[/blue]", "note": "[green]note[/green]", "web": "[magenta]web[/magenta]"}

    table = Table(
        title=f"収集済み投稿 ({len(posts)}件)",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("ID", style="dim", width=4, justify="right")
    table.add_column("Source", width=6, justify="center")
    table.add_column("著者", width=20)
    table.add_column("内容（先頭60文字）", width=60)
    table.add_column("いいね", width=7, justify="right")
    table.add_column("引用", width=5, justify="right")
    table.add_column("生成済", width=6, justify="center")

    for post in posts:
        content_preview = (post["content"] or "")[:60].replace("\n", " ")
        if len(post["content"] or "") > 60:
            content_preview += "..."

        source_label = source_colors.get(post["source"], post["source"])
        generated = "[green]✓[/green]" if post["generated_at"] else "[dim]-[/dim]"

        table.add_row(
            str(post["id"]),
            source_label,
            (post["author"] or "")[:20],
            content_preview,
            f"{post['like_count']:,}",
            str(post["quote_count"]),
            generated,
        )

    console.print(table)
    console.print(
        "\n[dim]詳細表示: python main.py show <ID>[/dim]\n"
        "[dim]コメント生成: python main.py generate <ID>[/dim]\n"
        "[dim]オリジナル投稿生成: python main.py original[/dim]"
    )


# ── show ─────────────────────────────────────────────────────────

@cli.command()
@click.argument("post_id", type=int)
def show(post_id: int):
    """投稿の詳細と生成済みコメントを表示する"""
    post = get_post_by_id(post_id)
    if not post:
        console.print(f"[red]ID {post_id} の投稿が見つかりません。[/red]")
        sys.exit(1)

    source_labels = {"x": "X (Twitter)", "note": "note.com", "web": "Web"}
    source_label = source_labels.get(post["source"], post["source"])
    metrics = (
        f"いいね: {post['like_count']:,}  引用: {post['quote_count']}  "
        f"RT: {post['retweet_count']}  返信: {post['reply_count']}"
    )

    console.print(
        Panel(
            f"[bold]{post['content']}[/bold]\n\n"
            f"[dim]著者: {post['author']}[/dim]\n"
            f"[dim]URL: {post['url']}[/dim]\n"
            f"[dim]{metrics}[/dim]\n"
            f"[dim]収集日時: {post['collected_at']}[/dim]",
            title=f"[bold cyan]投稿 ID:{post_id}  [{source_label}][/bold cyan]",
            border_style="cyan",
        )
    )

    comments = get_comments_for_post(post_id)
    if comments:
        console.print("\n[bold yellow]生成済み引用コメント[/bold yellow]")
        for c in comments:
            console.print(
                Panel(
                    c["comment"],
                    title=f"[dim]案{c['comment_number']}[/dim]",
                    border_style="yellow",
                )
            )
    else:
        console.print(
            f"\n[dim]まだコメントが生成されていません。"
            f"`python main.py generate {post_id}` で生成できます。[/dim]"
        )


# ── generate ─────────────────────────────────────────────────────

@cli.command()
@click.argument("post_id", type=int)
def generate(post_id: int):
    """指定した投稿IDに対して引用コメント5案を生成する"""
    post = get_post_by_id(post_id)
    if not post:
        console.print(f"[red]ID {post_id} の投稿が見つかりません。[/red]")
        sys.exit(1)

    _run_generate(post_id, post["content"] or "", post["author"] or "", post["url"] or "")


def _run_generate(post_id: int, content: str, author: str, url: str):
    """引用コメント生成の共通処理"""
    console.print(f"\n[cyan]引用コメントを生成中（ID:{post_id}）...[/cyan]")
    console.print(f"[dim]元投稿: {content[:80]}{'...' if len(content) > 80 else ''}[/dim]\n")

    try:
        from generator.comment_generator import CommentGenerator
        comments = CommentGenerator().generate(
            author=author,
            content=content,
            url=url,
        )
    except ValueError as e:
        console.print(f"[red]生成エラー: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]生成エラー: {e}[/red]")
        sys.exit(1)

    save_comments(post_id, comments)

    console.print("[bold green]引用コメント5案が生成されました！[/bold green]\n")
    for i, comment in enumerate(comments, start=1):
        console.print(
            Panel(
                comment,
                title=f"[bold yellow]案{i}[/bold yellow]",
                border_style="yellow",
            )
        )

    console.print(
        f"\n[dim]コメントはDBに保存されました。"
        f"`python main.py show {post_id}` で再確認できます。[/dim]"
    )


# ── original ─────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--show",
    "show_saved",
    is_flag=True,
    default=False,
    help="新規生成せず、前回生成したオリジナルポストを表示する",
)
@click.option(
    "--context-limit",
    default=30,
    show_default=True,
    help="コンテキストとして使う収集済み投稿の件数",
)
def original(show_saved: bool, context_limit: int):
    """蓄積した投稿コンテキストをもとにオリジナルポスト5案を生成する"""

    if show_saved:
        posts = get_original_posts()
        if not posts:
            console.print("[yellow]保存済みのオリジナルポストがありません。`original` を実行してください。[/yellow]")
            return
        _display_original_posts(posts)
        return

    # コンテキスト投稿を取得
    context_posts = get_posts_for_context(limit=context_limit)
    if not context_posts:
        console.print(
            "[yellow]コンテキストとなる投稿がありません。"
            "まず `add <URL>` または `collect` で投稿を保存してください。[/yellow]"
        )
        return

    console.print(
        f"[cyan]蓄積コンテキスト（{len(context_posts)}件）をもとにオリジナルポストを生成中...[/cyan]"
    )

    try:
        from generator.original_post_generator import OriginalPostGenerator
        posts_data = OriginalPostGenerator().generate(context_posts)
    except ValueError as e:
        console.print(f"[red]生成エラー: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]生成エラー: {e}[/red]")
        sys.exit(1)

    save_original_posts(posts_data)

    console.print("[bold green]オリジナルポスト5案が生成されました！[/bold green]\n")
    _display_original_posts(posts_data)

    console.print(
        "\n[dim]これらはDBに保存されました。"
        "`python main.py original --show` で再表示できます。[/dim]"
    )


def _display_original_posts(posts: list):
    type_labels = ["真実型", "対比型", "数字型", "問い型", "法則型"]
    for i, post in enumerate(posts):
        content = post.get("content", "") if isinstance(post, dict) else post["content"]
        theme = post.get("theme", "") if isinstance(post, dict) else post.get("theme", "")
        label_idx = (post.get("post_number", i + 1) - 1) if isinstance(post, dict) and "post_number" in post else i
        label = type_labels[label_idx] if label_idx < len(type_labels) else f"案{label_idx + 1}"

        subtitle = f" [dim]| テーマ: {theme}[/dim]" if theme else ""
        console.print(
            Panel(
                content,
                title=f"[bold green]{label}{subtitle}[/bold green]",
                border_style="green",
            )
        )


if __name__ == "__main__":
    cli()
