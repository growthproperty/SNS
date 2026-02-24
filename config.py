import os
from dotenv import load_dotenv

load_dotenv()

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

MIN_LIKE_COUNT = int(os.getenv("MIN_LIKE_COUNT", "1000"))
MIN_QUOTE_COUNT = int(os.getenv("MIN_QUOTE_COUNT", "100"))
MAX_RESULTS_PER_SEARCH = int(os.getenv("MAX_RESULTS_PER_SEARCH", "100"))

# X検索クエリ：ビジネス系・日本語の高エンゲージメント投稿
X_SEARCH_QUERIES = [
    "(経営 OR 起業 OR ビジネス) min_faves:1000 lang:ja -is:retweet",
    "(マーケティング OR 戦略 OR リーダーシップ) min_faves:1000 lang:ja -is:retweet",
    "(成長 OR 売上 OR 投資) (経営者 OR 社長 OR CEO) min_faves:1000 lang:ja -is:retweet",
]

# note.comのビジネスカテゴリ
NOTE_BUSINESS_CATEGORIES = ["business", "money"]
NOTE_MIN_LIKE_COUNT = 500
