#!/usr/bin/env python3
"""
バズ投稿収集 & 引用コメント生成ツール

使い方:
  python main.py collect          -- XとnoteからBuzz投稿を収集
  python main.py collect --source x    -- Xのみ収集
  python main.py collect --source note -- noteのみ収集
  python main.py list             -- 収集済み投稿を一覧表示
  python main.py list --source x  -- X投稿のみ表示
  python main.py show <ID>        -- 投稿の詳細と生成済みコメントを表示
  python main.py generate <ID>    -- 指定投稿の引用コメント5案を生成
"""

import sys
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from database.db import init_db, get_all_posts, get_post_by_id, save_comments, get_comments_for_post

console = Console()


@click.group()
def cli():
    """バズ投稿収集 & 引用コメント生成ツール"""
    init_db()


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
    """XとnoteからBuzz投稿を収集してDBに保存する"""

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


@cli.command("list")
@click.option(
    "--source",
    type=click.Choice(["x", "note", "all"]),
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
        console.print("[yellow]投稿が見つかりません。まず `collect` を実行してください。[/yellow]")
        return

    table = Table(
        title=f"収集済み投稿 ({len(posts)}件)",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("ID", style="dim", width=4, justify="right")
    table.add_column("Source", width=5, justify="center")
    table.add_column("著者", width=20)
    table.add_column("内容（先頭60文字）", width=60)
    table.add_column("いいね", width=7, justify="right")
    table.add_column("引用", width=5, justify="right")
    table.add_column("生成済", width=6, justify="center")

    for post in posts:
        content_preview = (post["content"] or "")[:60].replace("\n", " ")
        if len(post["content"] or "") > 60:
            content_preview += "..."

        source_label = "[blue]X[/blue]" if post["source"] == "x" else "[green]note[/green]"
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
        "[dim]コメント生成: python main.py generate <ID>[/dim]"
    )


@cli.command()
@click.argument("post_id", type=int)
def show(post_id: int):
    """投稿の詳細と生成済みコメントを表示する"""
    post = get_post_by_id(post_id)
    if not post:
        console.print(f"[red]ID {post_id} の投稿が見つかりません。[/red]")
        sys.exit(1)

    source_label = "X (Twitter)" if post["source"] == "x" else "note.com"
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
            "\n[dim]まだコメントが生成されていません。"
            f"`python main.py generate {post_id}` で生成できます。[/dim]"
        )


@cli.command()
@click.argument("post_id", type=int)
def generate(post_id: int):
    """指定した投稿IDに対して引用コメント5案を生成する"""
    post = get_post_by_id(post_id)
    if not post:
        console.print(f"[red]ID {post_id} の投稿が見つかりません。[/red]")
        sys.exit(1)

    console.print(f"[cyan]ID:{post_id} の引用コメントを生成中...[/cyan]")
    console.print(f"[dim]元投稿: {(post['content'] or '')[:80]}...[/dim]\n")

    try:
        from generator.comment_generator import CommentGenerator
        comments = CommentGenerator().generate(
            author=post["author"] or "",
            content=post["content"] or "",
            url=post["url"] or "",
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


if __name__ == "__main__":
    cli()
