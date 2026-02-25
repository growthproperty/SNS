"""
SQLiteデータベース管理モジュール
収集した投稿と生成したコメントを永続化する
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional

# DATA_DIR が設定されていればそこに保存（Fly.io等の永続ボリューム対応）
_data_dir = os.environ.get("DATA_DIR", os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(_data_dir, "sns_data.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """データベースとテーブルを初期化する"""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,          -- 'x', 'note', 'manual'
                post_id TEXT NOT NULL UNIQUE,  -- プラットフォーム上のID
                author TEXT,
                content TEXT NOT NULL,
                url TEXT NOT NULL,
                like_count INTEGER DEFAULT 0,
                quote_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                retweet_count INTEGER DEFAULT 0,
                impression_count INTEGER DEFAULT 0,
                insights TEXT,                 -- Claude抽出のテーマ/洞察（JSON）
                collected_at TEXT NOT NULL,
                generated_at TEXT              -- コメント生成日時
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS generated_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                comment_number INTEGER NOT NULL,  -- 1〜5
                comment TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS original_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_number INTEGER NOT NULL,  -- 1〜N
                content TEXT NOT NULL,
                theme TEXT,                    -- このポストが扱うテーマ
                created_at TEXT NOT NULL
            )
        """)
        # 既存DBへのマイグレーション（insightsカラムがない場合は追加）
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN insights TEXT")
        except Exception:
            pass
        conn.commit()


def save_post(
    source: str,
    post_id: str,
    author: str,
    content: str,
    url: str,
    like_count: int = 0,
    quote_count: int = 0,
    reply_count: int = 0,
    retweet_count: int = 0,
    impression_count: int = 0,
    insights: Optional[str] = None,
) -> Optional[int]:
    """投稿を保存する。既存のpost_idはスキップし、Noneを返す"""
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO posts
                    (source, post_id, author, content, url,
                     like_count, quote_count, reply_count, retweet_count,
                     impression_count, insights, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source, post_id, author, content, url,
                    like_count, quote_count, reply_count, retweet_count,
                    impression_count, insights, datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None


def update_post_insights(post_db_id: int, insights: str):
    """投稿のinsightsを更新する"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE posts SET insights = ? WHERE id = ?", (insights, post_db_id)
        )
        conn.commit()


def get_posts_for_context(limit: int = 30) -> list:
    """オリジナルポスト生成用にcontentとinsightsを含む投稿を取得する"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, source, author, content, url, insights FROM posts ORDER BY collected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def save_original_posts(posts: list[dict]):
    """生成されたオリジナルポストを保存する。posts = [{content, theme}]"""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute("DELETE FROM original_posts")
        for i, post in enumerate(posts, start=1):
            conn.execute(
                "INSERT INTO original_posts (post_number, content, theme, created_at) VALUES (?, ?, ?, ?)",
                (i, post.get("content", ""), post.get("theme", ""), now),
            )
        conn.commit()


def get_original_posts() -> list[dict]:
    """保存されたオリジナルポストを取得する"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM original_posts ORDER BY post_number"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_posts(source: Optional[str] = None, limit: int = 50) -> list:
    """収集済み投稿を新着順で取得する"""
    with get_connection() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM posts WHERE source = ? ORDER BY collected_at DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM posts ORDER BY collected_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_post_by_id(post_db_id: int) -> Optional[dict]:
    """DB上のIDで投稿を1件取得する"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM posts WHERE id = ?", (post_db_id,)
        ).fetchone()
        return dict(row) if row else None


def save_comments(post_db_id: int, comments: list[str]):
    """生成されたコメント5案を保存し、posts.generated_atを更新する"""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM generated_comments WHERE post_id = ?", (post_db_id,)
        )
        for i, comment in enumerate(comments, start=1):
            conn.execute(
                """
                INSERT INTO generated_comments (post_id, comment_number, comment, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (post_db_id, i, comment, now),
            )
        conn.execute(
            "UPDATE posts SET generated_at = ? WHERE id = ?", (now, post_db_id)
        )
        conn.commit()


def get_comments_for_post(post_db_id: int) -> list[dict]:
    """投稿に紐づく生成コメントを取得する"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM generated_comments WHERE post_id = ? ORDER BY comment_number",
            (post_db_id,),
        ).fetchall()
        return [dict(r) for r in rows]
