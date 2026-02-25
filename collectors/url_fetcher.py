"""
URL からコンテンツを取得するモジュール

対応URL:
  - X / Twitter: https://twitter.com/*/status/* または https://x.com/*/status/*
    → X Bearer Token があれば API 経由、なければ OG タグから取得
  - note.com  : https://note.com/*/n/*
    → HTML スクレイピング（OG タグ + 本文）
  - その他URL  : OG タグ（title / description）を取得
"""

import re
import hashlib
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


class FetchResult:
    """URL取得結果を表す値オブジェクト"""

    def __init__(
        self,
        source: str,
        post_id: str,
        author: str,
        content: str,
        url: str,
        like_count: int = 0,
        quote_count: int = 0,
        reply_count: int = 0,
        retweet_count: int = 0,
    ):
        self.source = source
        self.post_id = post_id
        self.author = author
        self.content = content
        self.url = url
        self.like_count = like_count
        self.quote_count = quote_count
        self.reply_count = reply_count
        self.retweet_count = retweet_count


def fetch_from_url(url: str) -> FetchResult:
    """
    URLからコンテンツを取得して FetchResult を返す。
    取得失敗時は RuntimeError を送出する。
    """
    url = url.strip()

    if _is_x_url(url):
        return _fetch_x(url)
    elif _is_note_url(url):
        return _fetch_note(url)
    else:
        return _fetch_generic(url)


# ── X (Twitter) ────────────────────────────────────────────────

def _is_x_url(url: str) -> bool:
    return bool(re.search(r"(twitter\.com|x\.com)/\S+/status/\d+", url))


def _extract_tweet_id(url: str) -> str | None:
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def _fetch_x(url: str) -> FetchResult:
    tweet_id = _extract_tweet_id(url)

    # X APIが利用可能な場合はAPI経由で取得
    try:
        from config import X_BEARER_TOKEN
        if X_BEARER_TOKEN:
            return _fetch_x_via_api(url, tweet_id)
    except Exception:
        pass

    # フォールバック: OGタグ取得
    return _fetch_x_via_og(url, tweet_id)


def _fetch_x_via_api(url: str, tweet_id: str | None) -> FetchResult:
    import tweepy
    from config import X_BEARER_TOKEN

    client = tweepy.Client(bearer_token=X_BEARER_TOKEN)
    response = client.get_tweet(
        id=tweet_id,
        tweet_fields=["public_metrics", "author_id"],
        expansions=["author_id"],
        user_fields=["name", "username"],
    )
    if not response.data:
        raise RuntimeError("X API: ツイートが取得できませんでした")

    tweet = response.data
    metrics = tweet.public_metrics or {}

    author = str(tweet.author_id)
    if response.includes and "users" in response.includes:
        user = response.includes["users"][0]
        author = f"@{user.username} ({user.name})"

    canonical_url = f"https://twitter.com/i/web/status/{tweet_id}"
    return FetchResult(
        source="x",
        post_id=str(tweet_id),
        author=author,
        content=tweet.text,
        url=canonical_url,
        like_count=metrics.get("like_count", 0),
        quote_count=metrics.get("quote_count", 0),
        reply_count=metrics.get("reply_count", 0),
        retweet_count=metrics.get("retweet_count", 0),
    )


def _fetch_x_via_og(url: str, tweet_id: str | None) -> FetchResult:
    """OGタグまたはHTMLからツイート内容を取得する（APIキー不要フォールバック）"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")

        # OG description に tweet本文が入ることがある
        og_desc = _og(soup, "description") or _og(soup, "og:description") or ""
        og_title = _og(soup, "og:title") or ""
        # author は og:title から "username on X: ..." パターンで取れることがある
        author = ""
        title_match = re.match(r"^(.+?) on X:", og_title)
        if title_match:
            author = title_match.group(1).strip()

        content = og_desc.strip() or og_title.strip()
        if not content:
            raise RuntimeError("X投稿の内容を取得できませんでした（X APIの設定を推奨します）")

        pid = tweet_id or _url_hash(url)
        return FetchResult(
            source="x",
            post_id=pid,
            author=author,
            content=content,
            url=url,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"X投稿の取得に失敗しました: {e}") from e


# ── note.com ────────────────────────────────────────────────────

def _is_note_url(url: str) -> bool:
    return "note.com" in url


def _fetch_note(url: str) -> FetchResult:
    """note記事をHTMLスクレイピングで取得する"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = _og(soup, "og:title") or ""
        description = _og(soup, "og:description") or ""
        author_name = _og(soup, "og:site_name") or ""

        # note の記事本文セレクタ（複数パターン試行）
        body_el = (
            soup.select_one("div.note-body")
            or soup.select_one("div[class*='note-common-styles']")
            or soup.select_one("article")
        )
        body_text = ""
        if body_el:
            body_text = body_el.get_text(separator="\n", strip=True)[:800]

        # authorはURLのusernameから取得
        m = re.match(r"https://note\.com/([^/]+)/", url)
        author_urlname = m.group(1) if m else ""

        # Twitter/OGのauthor metaを探す
        author_meta = soup.find("meta", attrs={"name": "author"})
        if author_meta and author_meta.get("content"):
            author_name = author_meta["content"]
        elif author_urlname:
            author_name = f"@{author_urlname}" if not author_name else author_name

        content = title
        if description:
            content += f"\n\n{description}"
        if body_text and body_text not in content:
            content += f"\n\n{body_text[:400]}"

        if not content.strip():
            raise RuntimeError("note記事の内容を取得できませんでした")

        # URLからpost_id生成（key部分）
        key_match = re.search(r"/n/([^/?#]+)", url)
        post_id = f"note_{key_match.group(1)}" if key_match else f"note_{_url_hash(url)}"

        return FetchResult(
            source="note",
            post_id=post_id,
            author=author_name,
            content=content.strip(),
            url=url,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"note記事の取得に失敗しました: {e}") from e


# ── 汎用URL ─────────────────────────────────────────────────────

def _fetch_generic(url: str) -> FetchResult:
    """OGタグ + 記事本文からコンテンツを取得する汎用フォールバック"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = (
            _og(soup, "og:title")
            or (soup.find("title").get_text(strip=True) if soup.find("title") else "")
        )
        description = _og(soup, "og:description") or ""
        author = _og(soup, "article:author") or ""

        # メイン本文を探す
        body_el = (
            soup.select_one("article")
            or soup.select_one("main")
            or soup.select_one('[role="main"]')
        )
        body_text = ""
        if body_el:
            body_text = body_el.get_text(separator="\n", strip=True)[:600]

        content = title
        if description:
            content += f"\n\n{description}"
        if body_text and body_text not in content:
            content += f"\n\n{body_text[:300]}"

        if not content.strip():
            raise RuntimeError("ページのコンテンツを取得できませんでした")

        return FetchResult(
            source="web",
            post_id=f"web_{_url_hash(url)}",
            author=author,
            content=content.strip(),
            url=url,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"URLの取得に失敗しました: {e}") from e


# ── ユーティリティ ────────────────────────────────────────────

def _og(soup: BeautifulSoup, prop: str) -> str:
    """OGタグ または name meta からコンテンツを取得する"""
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    if tag and tag.get("content"):
        return tag["content"]
    return ""


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]
