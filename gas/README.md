# SNS Bot - Google Apps Script 版セットアップ手順

**費用: $0（Anthropic APIの利用分のみ）**

---

## 必要なもの

- Googleアカウント（無料）
- LINEアカウント（無料）
- Anthropic APIキー（[console.anthropic.com](https://console.anthropic.com) で取得）

---

## STEP 1: Google スプレッドシートを作成

1. [Google スプレッドシート](https://sheets.google.com) を開く
2. 新しいスプレッドシートを作成（タイトルは「SNS Bot データ」など）
3. URLの `https://docs.google.com/spreadsheets/d/【ここ】/edit` の部分をコピーしてメモしておく

---

## STEP 2: Google Apps Script を作成

1. スプレッドシートを開いた状態で、メニューの **「拡張機能」→「Apps Script」** をクリック
2. 左側の `コード.gs` を選択して、**全テキストを削除**
3. このリポジトリの `gas/Code.gs` の内容を**まるごとコピー&ペースト**
4. 上部の **「保存」ボタン（Ctrl+S）** をクリック

---

## STEP 3: スクリプトプロパティを設定

1. Apps Script 画面の左メニューの **「プロジェクトの設定」（歯車アイコン）** をクリック
2. 下にスクロールして **「スクリプト プロパティ」→「スクリプト プロパティを追加」** をクリック
3. 以下の3つを追加する：

| プロパティ名 | 値 |
|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-xxxxxxxx`（Anthropic Consoleで取得） |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINEのチャンネルアクセストークン（後述） |
| `SPREADSHEET_ID` | STEP 1 でメモしたID |

---

## STEP 4: LINE Messaging API を設定

1. [LINE Developers Console](https://developers.line.biz/ja/) でログイン
2. **「プロバイダーを作成」** → **「Messaging API チャンネルを作成」**
3. チャンネル名・説明など入力して作成
4. **「Messaging API 設定」** タブ → **「チャンネルアクセストークン（長期）」→「発行」**
5. 発行されたトークンを STEP 3 の `LINE_CHANNEL_ACCESS_TOKEN` に設定

---

## STEP 5: セットアップ関数を実行

1. Apps Script 画面に戻る
2. 関数のプルダウンから **`setup`** を選択
3. **「▶ 実行」** ボタンをクリック
4. 権限承認を求めるダイアログが出たら **「権限を確認」→「許可」** をクリック
5. ログに「✅ セットアップ完了！」と表示されれば OK

---

## STEP 6: ウェブアプリとしてデプロイ

1. Apps Script 画面右上の **「デプロイ」→「新しいデプロイ」** をクリック
2. 種類の選択で **「ウェブアプリ」** を選択
3. 設定：
   - 説明: `SNS Bot`（任意）
   - 次のユーザーとして実行: **「自分」**
   - アクセスできるユーザー: **「全員」**
4. **「デプロイ」** をクリック
5. 表示された **ウェブアプリのURL** をコピーしてメモ（例: `https://script.google.com/macros/s/xxxxx/exec`）

---

## STEP 7: LINE Webhook URL を設定

1. [LINE Developers Console](https://developers.line.biz/ja/) → 作成したチャンネルを開く
2. **「Messaging API 設定」** タブ
3. **「Webhook URL」** に STEP 6 でメモした URL を入力
4. **「検証」** ボタンを押して「成功」と表示されればOK
5. **「Webhookの利用」** をオンにする
6. **「応答メッセージ」** はオフにする（Botが自動返信するため）

---

## STEP 8: LINE Bot を友達追加またはグループに追加

- **個人トークで使う場合**: Messaging API設定のQRコードから友達追加
- **グループで使う場合**:
  1. Messaging API設定で「グループ・複数人トークへの参加を許可する」をオンにする
  2. LINEのグループにBotを招待する

---

## 完成！使い方

LINEのトークで以下を送信：

```
https://x.com/user/status/xxxxxxx   → 保存 + 引用コメント5案
original                             → オリジナルポスト5案
list                                 → 最近の投稿一覧
show 3                               → ID:3の詳細
generate 3                           → ID:3のコメントを再生成
help                                 → 使い方表示
```

※ URLを送信してから結果が届くまで **1〜2分** かかります（GASのバックグラウンド処理のため）

---

## トラブルシューティング

### 「❌ コンテンツの取得に失敗しました」と表示される

X(Twitter)の投稿はログインしないと取得できないことがあります。
その場合は投稿の本文をコピーして、URLの代わりに直接テキストを送信してください。

### 返信が来ない

- LINE Developers Console で Webhook が有効になっているか確認
- Apps Script の「実行数」ページでエラーが出ていないか確認
- スクリプトプロパティが正しく設定されているか確認

### データはどこに保存される？

Google スプレッドシートに自動的に保存されます。
`posts`・`comments`・`original_posts`・`pending_jobs` の4つのシートが自動作成されます。
