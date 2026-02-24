"""
Claude API を使った引用コメント生成モジュール

収集した投稿に対して、引用リポスト用のコメント案を5つ生成する。
ターゲット: 経営者・ビジネスマン向けのビジネス系Xアカウント
"""

import anthropic
from config import ANTHROPIC_API_KEY

SYSTEM_PROMPT = """\
あなたは日本のビジネス系Xアカウントを運用するSNSマーケターです。
バズっているビジネス系の投稿・記事に対して、引用リポスト用のコメントを作成する専門家です。

【ターゲット読者】
- 20〜40代の男性ビジネスマン・経営者・起業家
- ビジネスの本質・経営哲学・成長戦略に興味がある層

【コメント作成の方針】
- 元投稿の本質をついた洞察・視点を加える
- 読者が「なるほど」「共感できる」と思う内容にする
- 具体的な経験・数字・事例を引用すると説得力が増す
- 問いかけや挑発的な視点を入れてエンゲージメントを高める
- 自分のフォロワーに有益な情報提供・気づきを与える
- X（旧Twitter）の文字数制限（140文字）以内に収める
- 自然な日本語で、硬くなりすぎない表現にする
- ハッシュタグは使わない（アルゴリズム上マイナスのため）

【各コメントのトーン（5案）】
1. 共感・補足型：元投稿に同意しつつ、さらなる洞察を加える
2. 問いかけ型：読者に考えさせる問いを投げかける
3. 具体化型：抽象的な内容を具体的な事例や数字で補強する
4. 反骨・逆説型：あえて別の角度から見た視点を示す
5. 行動促進型：読者が今すぐ行動したくなるような内容にする
"""

USER_PROMPT_TEMPLATE = """\
以下の投稿に対して、引用リポスト用のコメントを5案作成してください。

【元の投稿】
著者: {author}
内容:
{content}

URL: {url}

---

以下の形式で出力してください：

**案1（共感・補足型）**
[コメント本文]

**案2（問いかけ型）**
[コメント本文]

**案3（具体化型）**
[コメント本文]

**案4（反骨・逆説型）**
[コメント本文]

**案5（行動促進型）**
[コメント本文]

各コメントは140文字以内で、すぐにポストできるクオリティにしてください。
"""


class CommentGenerator:
    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY が設定されていません。.env ファイルを確認してください。"
            )
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def generate(self, author: str, content: str, url: str) -> list[str]:
        """
        投稿内容に対して引用コメント5案を生成する。

        Returns:
            5つのコメント文字列のリスト
        """
        prompt = USER_PROMPT_TEMPLATE.format(
            author=author or "不明",
            content=content,
            url=url,
        )

        message = self.client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = message.content[0].text
        return self._parse_comments(raw_text)

    def _parse_comments(self, raw_text: str) -> list[str]:
        """
        モデル出力から5案のコメントを抽出する。
        パース失敗時は生テキストを1案目として返す。
        """
        comments = []
        lines = raw_text.split("\n")
        current_comment_lines: list[str] = []
        in_comment = False

        for line in lines:
            stripped = line.strip()
            # 「**案N（〜）**」または「**案N:**」のような行をヘッダーとして検出
            is_header = (
                stripped.startswith("**案")
                and ("型" in stripped or ":" in stripped or "）" in stripped)
            )
            if is_header:
                if current_comment_lines:
                    comment = "\n".join(current_comment_lines).strip()
                    if comment:
                        comments.append(comment)
                    current_comment_lines = []
                in_comment = True
                continue
            if in_comment and stripped:
                current_comment_lines.append(stripped)

        # 最後のコメントを追加
        if current_comment_lines:
            comment = "\n".join(current_comment_lines).strip()
            if comment:
                comments.append(comment)

        # パース結果が不十分な場合のフォールバック
        if len(comments) < 3:
            return [raw_text]

        return comments[:5]
