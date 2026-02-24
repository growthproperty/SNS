"""
X (Twitter) API v2 を使ったバズ投稿収集モジュール

必要な認証情報:
  - X_BEARER_TOKEN: Twitter Developer Portal で取得した Bearer Token
  - API アクセスレベル: Basic 以上（月$100）が必要
    Free tier では search_recent_tweets が利用不可の場合あり

impressionについて:
  X API v2 では他ユーザーのインプレッション数は取得不可。
  代わりにいいね数(min_faves)と引用数(min_retweets相当)を基準に収集する。
"""

import tweepy
from config import (
    X_BEARER_TOKEN,
    MIN_LIKE_COUNT,
    MIN_QUOTE_COUNT,
    MAX_RESULTS_PER_SEARCH,
    X_SEARCH_QUERIES,
)
from database.db import save_post


class XCollector:
    def __init__(self):
        if not X_BEARER_TOKEN:
            raise ValueError(
                "X_BEARER_TOKEN が設定されていません。.env ファイルを確認してください。"
            )
        self.client = tweepy.Client(bearer_token=X_BEARER_TOKEN, wait_on_rate_limit=True)

    def collect(self) -> tuple[int, int]:
        """
        設定済みのクエリでバズ投稿を収集してDBに保存する。

        Returns:
            (saved_count, skipped_count): 新規保存数とスキップ数のタプル
        """
        saved = 0
        skipped = 0

        for query in X_SEARCH_QUERIES:
            try:
                response = self.client.search_recent_tweets(
                    query=query,
                    tweet_fields=[
                        "public_metrics",
                        "created_at",
                        "author_id",
                        "entities",
                    ],
                    expansions=["author_id"],
                    user_fields=["name", "username"],
                    max_results=min(MAX_RESULTS_PER_SEARCH, 100),
                )
            except tweepy.errors.TweepyException as e:
                print(f"[X] API エラー (query={query!r}): {e}")
                continue

            if not response.data:
                continue

            # author情報をマップ化
            author_map: dict[str, str] = {}
            if response.includes and "users" in response.includes:
                for user in response.includes["users"]:
                    author_map[str(user.id)] = f"@{user.username} ({user.name})"

            for tweet in response.data:
                metrics = tweet.public_metrics or {}
                like_count = metrics.get("like_count", 0)
                quote_count = metrics.get("quote_count", 0)
                reply_count = metrics.get("reply_count", 0)
                retweet_count = metrics.get("retweet_count", 0)

                # エンゲージメントフィルタ
                if like_count < MIN_LIKE_COUNT or quote_count < MIN_QUOTE_COUNT:
                    continue

                author = author_map.get(str(tweet.author_id), str(tweet.author_id))
                url = f"https://twitter.com/i/web/status/{tweet.id}"

                result = save_post(
                    source="x",
                    post_id=str(tweet.id),
                    author=author,
                    content=tweet.text,
                    url=url,
                    like_count=like_count,
                    quote_count=quote_count,
                    reply_count=reply_count,
                    retweet_count=retweet_count,
                )
                if result is not None:
                    saved += 1
                else:
                    skipped += 1

        return saved, skipped
