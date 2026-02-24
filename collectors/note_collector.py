"""
note.com 人気記事収集モジュール

note の公開カテゴリAPIを利用してビジネス系の人気記事を収集する。
APIキー不要（公開エンドポイント）。
"""

import requests
from config import NOTE_BUSINESS_CATEGORIES, NOTE_MIN_LIKE_COUNT
from database.db import save_post

NOTE_API_BASE = "https://note.com/api/v2"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


class NoteCollector:
    def collect(self, pages: int = 3) -> tuple[int, int]:
        """
        ビジネスカテゴリの人気記事を収集してDBに保存する。

        Args:
            pages: 取得するページ数（1ページ = 最大20件）

        Returns:
            (saved_count, skipped_count)
        """
        saved = 0
        skipped = 0

        for category in NOTE_BUSINESS_CATEGORIES:
            for page in range(1, pages + 1):
                articles = self._fetch_popular_articles(category, page)
                if not articles:
                    break

                for article in articles:
                    like_count = article.get("likeCount", 0)
                    if like_count < NOTE_MIN_LIKE_COUNT:
                        continue

                    post_id = str(article.get("id", ""))
                    if not post_id:
                        continue

                    key = article.get("key", "")
                    user = article.get("user", {})
                    author_name = user.get("nickname", "")
                    author_urlname = user.get("urlname", "")
                    author = f"{author_name} (@{author_urlname})" if author_urlname else author_name

                    title = article.get("name", "")
                    body = article.get("body", "") or ""
                    # bodyが長い場合は先頭500文字に制限
                    content = title + ("\n\n" + body[:500] if body else "")

                    url = f"https://note.com/{author_urlname}/n/{key}" if key and author_urlname else ""
                    if not url:
                        continue

                    result = save_post(
                        source="note",
                        post_id=f"note_{post_id}",
                        author=author,
                        content=content,
                        url=url,
                        like_count=like_count,
                    )
                    if result is not None:
                        saved += 1
                    else:
                        skipped += 1

        return saved, skipped

    def _fetch_popular_articles(self, category: str, page: int) -> list[dict]:
        """note カテゴリAPIから人気記事リストを取得する"""
        url = f"{NOTE_API_BASE}/categories/{category}/contents"
        params = {"kind": "note", "page": page}

        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("contents", [])
        except requests.exceptions.HTTPError as e:
            print(f"[note] HTTP エラー (category={category}, page={page}): {e}")
            return []
        except requests.exceptions.RequestException as e:
            print(f"[note] 通信エラー (category={category}, page={page}): {e}")
            return []
        except (KeyError, ValueError) as e:
            print(f"[note] レスポンス解析エラー: {e}")
            return []
