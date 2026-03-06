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

  --- 確定申告サポート ---
  python main.py tax add-income    -- 収入を登録
  python main.py tax add-expense   -- 経費を登録
  python main.py tax list          -- 収入・経費の一覧表示
  python main.py tax delete        -- エントリを削除
  python main.py tax summary       -- 年間集計と税額試算
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
    add_tax_income,
    add_tax_expense,
    delete_tax_entry,
    get_tax_income,
    get_tax_expense,
    get_tax_summary,
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


# ── tax ──────────────────────────────────────────────────────────────

@cli.group()
def tax():
    """確定申告サポート：収入・経費の管理と税額試算"""


@tax.command("add-income")
@click.option("--year",     type=int,   required=True, help="年（例: 2025）")
@click.option("--month",    type=int,   required=True, help="月（1〜12）")
@click.option("--amount",   type=int,   required=True, help="金額（円）")
@click.option(
    "--category",
    default="その他収入",
    show_default=True,
    help="収入カテゴリ",
)
@click.option("--note",     default="", help="摘要（任意）")
def tax_add_income(year: int, month: int, amount: int, category: str, note: str):
    """収入を登録する"""
    from tax.calculator import INCOME_CATEGORIES
    if category not in INCOME_CATEGORIES:
        console.print(f"[yellow]カテゴリ一覧: {', '.join(INCOME_CATEGORIES)}[/yellow]")
    entry_id = add_tax_income(year, month, amount, category, note)
    console.print(
        f"[green]収入を登録しました（ID:{entry_id}）[/green] "
        f"[dim]{year}/{month:02d}  {amount:,}円  [{category}]  {note}[/dim]"
    )


@tax.command("add-expense")
@click.option("--year",     type=int,   required=True, help="年（例: 2025）")
@click.option("--month",    type=int,   required=True, help="月（1〜12）")
@click.option("--amount",   type=int,   required=True, help="金額（円）")
@click.option(
    "--category",
    default="その他経費",
    show_default=True,
    help="経費カテゴリ",
)
@click.option("--note",     default="", help="摘要（任意）")
def tax_add_expense(year: int, month: int, amount: int, category: str, note: str):
    """経費を登録する"""
    from tax.calculator import EXPENSE_CATEGORIES
    if category not in EXPENSE_CATEGORIES:
        console.print(f"[yellow]カテゴリ一覧: {', '.join(EXPENSE_CATEGORIES)}[/yellow]")
    entry_id = add_tax_expense(year, month, amount, category, note)
    console.print(
        f"[green]経費を登録しました（ID:{entry_id}）[/green] "
        f"[dim]{year}/{month:02d}  {amount:,}円  [{category}]  {note}[/dim]"
    )


@tax.command("list")
@click.option("--year", type=int, default=None, help="対象年（省略時は当年）")
@click.option(
    "--type",
    "entry_type",
    type=click.Choice(["income", "expense", "all"]),
    default="all",
    show_default=True,
    help="表示種別",
)
def tax_list(year: int, entry_type: str):
    """収入・経費の一覧を表示する"""
    import datetime as dt
    if year is None:
        year = dt.date.today().year

    def _print_table(title: str, rows: list, color: str):
        if not rows:
            console.print(f"[dim]{title}: データなし[/dim]")
            return
        table = Table(title=f"{title} ({year}年)", box=box.ROUNDED, show_lines=True)
        table.add_column("ID",       style="dim",   width=5,  justify="right")
        table.add_column("月",       width=4,  justify="right")
        table.add_column("金額（円）", width=12, justify="right")
        table.add_column("カテゴリ", width=20)
        table.add_column("摘要",     width=30)
        for r in rows:
            table.add_row(
                str(r["id"]),
                str(r["month"]),
                f"[{color}]{r['amount']:,}[/{color}]",
                r["category"],
                r["note"] or "",
            )
        console.print(table)

    if entry_type in ("income", "all"):
        _print_table("収入", get_tax_income(year), "green")
    if entry_type in ("expense", "all"):
        _print_table("経費", get_tax_expense(year), "red")


@tax.command("delete")
@click.option(
    "--type",
    "entry_type",
    type=click.Choice(["income", "expense"]),
    required=True,
    help="削除対象の種別",
)
@click.option("--id", "entry_id", type=int, required=True, help="削除するエントリのID")
def tax_delete(entry_type: str, entry_id: int):
    """収入または経費のエントリを削除する"""
    if delete_tax_entry(entry_type, entry_id):
        label = "収入" if entry_type == "income" else "経費"
        console.print(f"[green]{label} ID:{entry_id} を削除しました。[/green]")
    else:
        console.print(f"[red]ID:{entry_id} が見つかりません。[/red]")


@tax.command("summary")
@click.option("--year", type=int, default=None, help="対象年（省略時は当年）")
@click.option(
    "--no-blue",
    is_flag=True,
    default=False,
    help="青色申告特別控除を使わない（白色申告）",
)
@click.option(
    "--blue-simple",
    is_flag=True,
    default=False,
    help="青色申告・簡易簿記（10万円控除）を使う",
)
def tax_summary(year: int, no_blue: bool, blue_simple: bool):
    """年間の収入・経費を集計し、所得税・住民税を試算する"""
    import datetime as dt
    from tax.calculator import calculate

    if year is None:
        year = dt.date.today().year

    data = get_tax_summary(year)

    use_blue = not no_blue
    blue_full = not blue_simple

    result = calculate(
        year=year,
        total_income=data["total_income"],
        total_expense=data["total_expense"],
        use_blue_return=use_blue,
        blue_return_full=blue_full,
    )

    # ── 収入内訳 ──
    if data["income_by_category"]:
        t = Table(title=f"収入内訳 ({year}年)", box=box.SIMPLE, show_header=True)
        t.add_column("カテゴリ", width=24)
        t.add_column("合計（円）", justify="right", width=14)
        for row in data["income_by_category"]:
            t.add_row(row["category"], f"{row['total']:,}")
        console.print(t)

    # ── 経費内訳 ──
    if data["expense_by_category"]:
        t = Table(title=f"経費内訳 ({year}年)", box=box.SIMPLE, show_header=True)
        t.add_column("カテゴリ", width=24)
        t.add_column("合計（円）", justify="right", width=14)
        for row in data["expense_by_category"]:
            t.add_row(row["category"], f"{row['total']:,}")
        console.print(t)

    # ── 税額試算 ──
    blue_label = "なし（白色）" if not use_blue else ("65万円（電子申告）" if blue_full else "10万円（簡易簿記）")
    console.print(
        Panel(
            f"[bold]年間収入合計    [/bold]  [green]{result.total_income:>14,} 円[/green]\n"
            f"[bold]年間経費合計    [/bold]  [red]{result.total_expense:>14,} 円[/red]\n"
            f"[bold]事業所得        [/bold]  {result.gross_profit:>14,} 円\n"
            f"[bold]青色申告特別控除[/bold]  [dim]{result.blue_return_deduction:>14,} 円  ({blue_label})[/dim]\n"
            f"[bold]基礎控除        [/bold]  [dim]{result.basic_deduction:>14,} 円[/dim]\n"
            f"─────────────────────────────────────────\n"
            f"[bold]課税所得        [/bold]  [yellow]{result.taxable_income:>14,} 円[/yellow]\n"
            f"─────────────────────────────────────────\n"
            f"[bold]所得税          [/bold]  [cyan]{result.income_tax:>14,} 円[/cyan]\n"
            f"[bold]復興特別所得税  [/bold]  [cyan]{result.reconstruction_tax:>14,} 円[/cyan]\n"
            f"[bold]住民税（所得割）[/bold]  [cyan]{result.resident_tax:>14,} 円[/cyan]\n"
            f"─────────────────────────────────────────\n"
            f"[bold]合計税額（概算）[/bold]  [bold red]{result.total_tax:>14,} 円[/bold red]\n"
            f"[bold]実効税率        [/bold]  [bold]{result.effective_rate:>13.1f} %[/bold]\n"
            f"\n[dim]※ 住民税は均等割（5,000円程度）を含まない概算です。"
            f"社会保険料控除・医療費控除等は別途考慮してください。[/dim]",
            title=f"[bold yellow]{year}年 確定申告 税額試算[/bold yellow]",
            border_style="yellow",
        )
    )

    if data["total_income"] == 0:
        console.print(
            "[dim]収入データがありません。"
            "`python main.py tax add-income` で収入を登録してください。[/dim]"
        )


if __name__ == "__main__":
    cli()
