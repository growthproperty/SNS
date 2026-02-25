"""
蓄積したコンテキストをもとにオリジナルポストを生成するモジュール

蓄積された投稿群のテーマ・洞察を分析し、
自力でエンゲージメントの高いオリジナルツイートを生成する。
"""

import json
import anthropic
from config import ANTHROPIC_API_KEY

INSIGHTS_SYSTEM_PROMPT = """\
あなたはビジネス系SNS分析の専門家です。
提供された投稿・記事のリストを分析して、各コンテンツから本質的なビジネス洞察を抽出してください。

出力はJSON形式で、以下の構造にしてください：
{
  "themes": ["テーマ1", "テーマ2", ...],
  "key_insights": ["洞察1", "洞察2", ...],
  "audience_pain_points": ["悩み1", "悩み2", ...],
  "tone": "投稿のトーン（例: 本質的・直接的・挑戦的）"
}

themes は5個以内、key_insights は7個以内で簡潔に。
"""

ORIGINAL_POST_SYSTEM_PROMPT = """\
あなたは日本のビジネス系Xアカウントの投稿者です。
月商1億円以上の経営者や急成長中の起業家が好む、本質的なビジネス投稿を書く専門家です。

【ターゲット】
- 20〜40代の男性ビジネスマン・経営者・起業家・ビジネスに真剣な会社員
- 仕事の本質、お金の真実、成長の法則に興味がある層

【オリジナルポストの作成方針】
- 誰かの引用ではなく、あなた自身の言葉として語る
- 「当たり前のことを、当たり前でない角度から言う」
- 具体的な数字・体験・対比を使って説得力を出す
- 読んだ人が「これは保存しておきたい」「これをシェアしたい」と思う内容
- 短く鋭く。ダラダラ説明しない
- 140文字以内（Xの文字数制限）に収める
- ハッシュタグは使わない
- 自然な日本語

【生成するポストの種類（各1案）】
1. 真実型：世の中の見落とされがちなビジネスの真実を断言する
2. 対比型：「〇〇な人」vs「△△な人」で本質的な違いを描く
3. 数字型：具体的な数字やデータを使って読者の認識を変える
4. 問い型：ビジネスマンが思わず立ち止まって考えたくなる問いを投げる
5. 法則型：成功・失敗のパターンを「〜する人は〜になる」形で言い切る
"""

ORIGINAL_POST_USER_TEMPLATE = """\
以下の分析データをもとに、オリジナルのビジネス系ツイートを5案作成してください。

【蓄積されたコンテキスト分析】
{context_analysis}

【参照した投稿・記事のサンプル（最新5件）】
{sample_posts}

---

上記のコンテキストを「吸収した経営者の視点」として内面化し、
完全にオリジナルのツイートを5案生成してください。
特定の投稿を引用・参照するのではなく、そこから得た洞察を自分の言葉で表現してください。

以下の形式で出力してください：

**1. 真実型**
[ツイート本文]
テーマ: [このツイートが扱うテーマ]

**2. 対比型**
[ツイート本文]
テーマ: [このツイートが扱うテーマ]

**3. 数字型**
[ツイート本文]
テーマ: [このツイートが扱うテーマ]

**4. 問い型**
[ツイート本文]
テーマ: [このツイートが扱うテーマ]

**5. 法則型**
[ツイート本文]
テーマ: [このツイートが扱うテーマ]

各ツイートは140文字以内で、今すぐポストできるクオリティにしてください。
"""


class OriginalPostGenerator:
    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY が設定されていません。.env ファイルを確認してください。"
            )
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def extract_insights(self, posts: list[dict]) -> str:
        """
        投稿リストからテーマ・洞察をJSON形式で抽出する。
        各投稿のinsightsフィールドに保存するための処理。
        """
        if not posts:
            return "{}"

        posts_text = "\n\n".join(
            f"[{p.get('source', '')}] {p.get('author', '')}\n{p.get('content', '')[:300]}"
            for p in posts[:10]
        )

        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=INSIGHTS_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"以下の投稿を分析してください：\n\n{posts_text}",
                }
            ],
        )
        return message.content[0].text

    def generate(self, posts: list[dict]) -> list[dict]:
        """
        蓄積した投稿コンテキストからオリジナルポストを5案生成する。

        Args:
            posts: DBから取得した投稿リスト（get_posts_for_context の結果）

        Returns:
            [{"content": "...", "theme": "..."}, ...] のリスト
        """
        if not posts:
            raise ValueError("コンテキストとなる投稿がありません。まず `add` または `collect` で投稿を保存してください。")

        # コンテキスト分析
        context_analysis = self._build_context_analysis(posts)

        # 最新5件のサンプル投稿
        sample_posts = "\n\n".join(
            f"---\n著者: {p.get('author', '不明')}\n{p.get('content', '')[:200]}"
            for p in posts[:5]
        )

        prompt = ORIGINAL_POST_USER_TEMPLATE.format(
            context_analysis=context_analysis,
            sample_posts=sample_posts,
        )

        message = self.client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            system=ORIGINAL_POST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_original_posts(message.content[0].text)

    def _build_context_analysis(self, posts: list[dict]) -> str:
        """投稿のinsightsフィールドを集約して分析テキストを作る"""
        all_themes: list[str] = []
        all_insights: list[str] = []
        all_pain_points: list[str] = []

        for post in posts:
            raw_insights = post.get("insights", "")
            if not raw_insights:
                continue
            try:
                data = json.loads(raw_insights)
                all_themes.extend(data.get("themes", []))
                all_insights.extend(data.get("key_insights", []))
                all_pain_points.extend(data.get("audience_pain_points", []))
            except (json.JSONDecodeError, AttributeError):
                continue

        # 重複を除いてまとめる
        themes_str = "、".join(list(dict.fromkeys(all_themes))[:8])
        insights_str = "\n".join(f"- {i}" for i in list(dict.fromkeys(all_insights))[:10])
        pain_str = "\n".join(f"- {p}" for p in list(dict.fromkeys(all_pain_points))[:6])

        if not themes_str and not insights_str:
            # insightsがない場合は投稿内容を直接まとめる
            content_summary = "\n\n".join(
                p.get("content", "")[:150] for p in posts[:8]
            )
            return f"収集済み投稿の内容サマリー:\n{content_summary}"

        return (
            f"頻出テーマ: {themes_str or '未分類'}\n\n"
            f"主要な洞察:\n{insights_str or '（なし）'}\n\n"
            f"読者の悩み・課題:\n{pain_str or '（なし）'}"
        )

    def _parse_original_posts(self, raw_text: str) -> list[dict]:
        """
        モデル出力から5案のオリジナルポストを抽出する。
        フォーマット: **N. タイプ名**\n[本文]\nテーマ: ...
        """
        posts: list[dict] = []
        lines = raw_text.split("\n")
        current_content_lines: list[str] = []
        current_theme = ""
        in_post = False

        for line in lines:
            stripped = line.strip()

            is_header = bool(re.match(r"\*\*\d+[.\s]", stripped))
            is_theme_line = stripped.startswith("テーマ:")

            if is_header:
                if current_content_lines:
                    content = "\n".join(current_content_lines).strip()
                    if content:
                        posts.append({"content": content, "theme": current_theme})
                current_content_lines = []
                current_theme = ""
                in_post = True
                continue

            if is_theme_line and in_post:
                current_theme = stripped.replace("テーマ:", "").strip()
                continue

            if in_post and stripped and not is_theme_line:
                current_content_lines.append(stripped)

        # 最後の投稿
        if current_content_lines:
            content = "\n".join(current_content_lines).strip()
            if content:
                posts.append({"content": content, "theme": current_theme})

        if len(posts) < 2:
            return [{"content": raw_text, "theme": ""}]

        return posts[:5]
