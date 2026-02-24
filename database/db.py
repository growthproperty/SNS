"""
SQLiteデータベース管理モジュール
収集した投稿と生成したコメントを永続化する
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sns_data.db")


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
                source TEXT NOT NULL,          -- 'x' or 'note'
                post_id TEXT NOT NULL UNIQUE,  -- プラットフォーム上のID
                author TEXT,
                content TEXT NOT NULL,
                url TEXT NOT NULL,
                like_count INTEGER DEFAULT 0,
                quote_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                retweet_count INTEGER DEFAULT 0,
                impression_count INTEGER DEFAULT 0,
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
) -> Optional[int]:
    """投稿を保存する。既存のpost_idはスキップし、Noneを返す"""
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO posts
                    (source, post_id, author, content, url,
                     like_count, quote_count, reply_count, retweet_count,
                     impression_count, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source, post_id, author, content, url,
                    like_count, quote_count, reply_count, retweet_count,
                    impression_count, datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None


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
