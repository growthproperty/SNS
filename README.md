# SNS バズ投稿収集 & 引用コメント生成ツール

X（旧Twitter）とnote.comから高エンゲージメントのビジネス系投稿を収集し、
Claude APIで引用リポスト用コメント案を自動生成するCLIツールです。

## セットアップ

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して以下を設定してください：

| 変数名 | 説明 | 必須 |
|--------|------|------|
| `X_BEARER_TOKEN` | X (Twitter) API v2 Bearer Token | X収集時のみ |
| `ANTHROPIC_API_KEY` | Anthropic API Key | コメント生成時 |

### APIキーの取得方法

- **X Bearer Token**: [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
  - **Basic tier（月$100）以上が必要**（Free tierではsearch APIが利用不可）
- **Anthropic API Key**: [Anthropic Console](https://console.anthropic.com/)

---

## 使い方

### 投稿の収集

```bash
# XとnoteからBuzz投稿を収集（両方）
python main.py collect

# Xのみ収集
python main.py collect --source x

# noteのみ収集（APIキー不要）
python main.py collect --source note

# noteで取得ページ数を指定（デフォルト3ページ ≒ 60件）
python main.py collect --source note --pages 5
```

### 収集済み投稿の確認

```bash
# 一覧表示
python main.py list

# X投稿のみ
python main.py list --source x

# note投稿のみ、50件まで表示
python main.py list --source note --limit 50

# 投稿の詳細を表示（コメント生成済みの場合はコメントも表示）
python main.py show 3
```

### 引用コメントの生成

```bash
# ID:3 の投稿に対してコメント5案を生成
python main.py generate 3
```

生成されるコメントの5タイプ：

| # | タイプ | 説明 |
|---|--------|------|
| 案1 | 共感・補足型 | 元投稿に同意しつつ洞察を加える |
| 案2 | 問いかけ型 | 読者に考えさせる問いを投げかける |
| 案3 | 具体化型 | 事例や数字で補強する |
| 案4 | 反骨・逆説型 | 別の角度からの視点を示す |
| 案5 | 行動促進型 | 今すぐ行動したくなる内容 |

---

## 技術仕様

### 収集基準

| プラットフォーム | フィルタ条件 |
|-----------------|-------------|
| X (Twitter) | いいね数 ≥ 1,000 かつ 引用数 ≥ 100（※impression数は他者のツイートでは取得不可） |
| note.com | いいね数 ≥ 500（ビジネス・マネーカテゴリ） |

### ファイル構成

```
SNS/
├── main.py               # CLIエントリーポイント
├── config.py             # 設定管理
├── requirements.txt
├── .env.example
├── database/
│   └── db.py             # SQLite操作
├── collectors/
│   ├── x_collector.py    # X API v2 収集
│   └── note_collector.py # note.com 収集
└── generator/
    └── comment_generator.py  # Claude API コメント生成
```

データは `sns_data.db`（SQLite）に保存されます。

---

## 注意事項

- X APIのimpressionは**投稿者自身のアカウント**でしか取得できないため、
  他者の投稿のimpressionは収集不可です。いいね数・引用数を代替指標として使用します。
- X Basic tier以上のAPIアクセスが必要です（月$100）。
- note.comのAPIは公開エンドポイントを使用しており、APIキーは不要です。
