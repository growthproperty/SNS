// ═══════════════════════════════════════════════════════════════
// SNS Bot - Google Apps Script 版
// サーバー不要・完全無料で動作するLINE Bot
//
// セットアップ手順は gas/README.md を参照
// ═══════════════════════════════════════════════════════════════

// ── 設定取得（スクリプトプロパティから） ─────────────────────────
const PROPS = PropertiesService.getScriptProperties();
function getLineToken()    { return PROPS.getProperty('LINE_CHANNEL_ACCESS_TOKEN'); }
function getAnthropicKey() { return PROPS.getProperty('ANTHROPIC_API_KEY'); }
function getSpreadsheetId(){ return PROPS.getProperty('SPREADSHEET_ID'); }

const CLAUDE_OPUS  = 'claude-opus-4-5';
const CLAUDE_HAIKU = 'claude-haiku-4-5-20251001';

// ── LINE Webhook エントリーポイント ───────────────────────────────
function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    (body.events || []).forEach(handleEvent);
  } catch (err) {
    Logger.log('doPost error: ' + err);
  }
  // LINEには即座に200を返す（処理はバックグラウンドトリガーへ）
  return ContentService.createTextOutput('OK');
}

function handleEvent(event) {
  if (event.type !== 'message' || event.message.type !== 'text') return;

  const text  = event.message.text.trim();
  const token = event.replyToken;
  const dest  = getDestination(event.source);
  const cmd   = text.toLowerCase();

  // ── URL が送られてきた場合 ────────────────────────────────────
  if (/^https?:\/\/\S+/.test(text)) {
    lineReply(token, '🔍 コンテンツを取得中...\n引用コメントは1〜2分後に送ります！');
    addPendingJob('url', text.match(/^https?:\/\/\S+/)[0], dest);
    return;
  }

  // ── original / オリジナル ────────────────────────────────────
  if (['original', 'オリジナル', 'orig'].includes(cmd)) {
    const count = countPosts();
    if (count === 0) {
      lineReply(token, '投稿がまだありません。URLを送信して追加してください。');
      return;
    }
    lineReply(token, `⚡ ${count}件のコンテキストからオリジナルポストを生成中...\n1〜2分後に送ります！`);
    addPendingJob('original', '', dest);
    return;
  }

  // ── list / 一覧 ───────────────────────────────────────────────
  if (['list', '一覧', 'リスト', 'ls'].includes(cmd)) {
    lineReply(token, buildListMessage());
    return;
  }

  // ── show <ID> ────────────────────────────────────────────────
  const showMatch = cmd.match(/^show\s+(\d+)$/);
  if (showMatch) {
    lineReply(token, buildShowMessage(parseInt(showMatch[1])));
    return;
  }

  // ── generate <ID> ────────────────────────────────────────────
  const genMatch = cmd.match(/^gen(?:erate)?\s+(\d+)$/);
  if (genMatch) {
    const postId = parseInt(genMatch[1]);
    if (!getPostById(postId)) {
      lineReply(token, `ID:${postId} の投稿が見つかりません。\n「list」で一覧を確認してください。`);
      return;
    }
    lineReply(token, `🔄 ID:${postId} のコメントを再生成中...\n1〜2分後に送ります！`);
    addPendingJob('generate', String(postId), dest);
    return;
  }

  // ── help ─────────────────────────────────────────────────────
  if (['help', 'ヘルプ', '使い方', '?', '？'].includes(cmd)) {
    lineReply(token, getHelpText());
    return;
  }

  lineReply(token, 'URLを送ると引用コメントを生成します📱\n「help」で使い方を確認できます');
}

// ── バックグラウンド処理（1分ごとのトリガーで実行） ─────────────────
function processPendingJobs() {
  const sheet = getSheet('pending_jobs');
  const data  = sheet.getDataRange().getValues();
  if (data.length <= 1) return;

  for (let i = 1; i < data.length; i++) {
    const [id, type, jobData, dest, , status] = data[i];
    if (status !== 'pending') continue;

    // 処理中マーク（重複防止）
    sheet.getRange(i + 1, 6).setValue('processing');
    SpreadsheetApp.flush();

    try {
      if (type === 'url')      processUrlJob(jobData, dest);
      if (type === 'original') processOriginalJob(dest);
      if (type === 'generate') processGenerateJob(parseInt(jobData), dest);
      sheet.getRange(i + 1, 6).setValue('done');
    } catch (err) {
      Logger.log(`Job ${id} error: ${err}`);
      sheet.getRange(i + 1, 6).setValue('error');
      linePush(dest, `❌ 処理エラー: ${err.message || err}`);
    }

    SpreadsheetApp.flush();
    break; // 1回に1件ずつ処理してタイムアウトを防ぐ
  }
}

// ── URL処理ジョブ ─────────────────────────────────────────────────
function processUrlJob(url, dest) {
  const fetched = fetchUrlContent(url);
  if (!fetched || !fetched.content) {
    linePush(dest, `❌ コンテンツの取得に失敗しました。\nXの投稿はログイン必須のため取得できない場合があります。\n${url}`);
    return;
  }

  const postId = savePost(fetched.source, fetched.postId, fetched.author, fetched.content, url);

  const icon = { x: '𝕏', note: '📝', web: '🌐' }[fetched.source] || '📄';
  linePush(dest,
    `${icon} 保存完了（ID:${postId}）\n\n` +
    `👤 ${fetched.author || '不明'}\n` +
    `${String(fetched.content).substring(0, 120)}${fetched.content.length > 120 ? '...' : ''}`
  );

  // 洞察抽出（Haiku：高速・安価）
  try {
    const insights = extractInsights(fetched.content, fetched.author, fetched.source);
    updatePostInsights(postId, insights);
  } catch (e) {
    Logger.log('insights error: ' + e);
  }

  // 引用コメント生成（Opus：高品質）
  const comments = generateComments(fetched.author, fetched.content, url);
  saveComments(postId, comments);

  const labels = ['共感・補足型', '問いかけ型', '具体化型', '反骨・逆説型', '行動促進型'];
  let msg = '💬 引用コメント5案\n\n';
  comments.forEach((c, i) => { msg += `【案${i+1} ${labels[i]||''}】\n${c}\n\n`; });
  linePush(dest, msg.trim());
}

// ── originalジョブ ────────────────────────────────────────────────
function processOriginalJob(dest) {
  const posts   = getPostsForContext(30);
  const results = generateOriginalPosts(posts);
  saveOriginalPosts(results);

  const typeLabels = ['真実型', '対比型', '数字型', '問い型', '法則型'];
  let msg = '🔥 オリジナルポスト5案\n\n';
  results.forEach((p, i) => {
    const label = typeLabels[i] || `案${i+1}`;
    const theme = p.theme ? `（${p.theme}）` : '';
    msg += `【${label}${theme}】\n${p.content}\n\n`;
  });
  linePush(dest, msg.trim());
}

// ── generateジョブ ────────────────────────────────────────────────
function processGenerateJob(postId, dest) {
  const post = getPostById(postId);
  if (!post) { linePush(dest, `ID:${postId} の投稿が見つかりません。`); return; }

  const comments = generateComments(post.author, post.content, post.url);
  saveComments(postId, comments);

  const labels = ['共感・補足型', '問いかけ型', '具体化型', '反骨・逆説型', '行動促進型'];
  let msg = `💬 ID:${postId} 引用コメント5案（再生成）\n\n`;
  comments.forEach((c, i) => { msg += `【案${i+1} ${labels[i]||''}】\n${c}\n\n`; });
  linePush(dest, msg.trim());
}

// ── URLコンテンツ取得 ─────────────────────────────────────────────
function fetchUrlContent(url) {
  const headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ja,en-US;q=0.9',
  };

  let response;
  try {
    response = UrlFetchApp.fetch(url, { headers, muteHttpExceptions: true, followRedirects: true });
  } catch (e) {
    return null;
  }

  const html = response.getContentText('UTF-8');

  // OGタグを取得するヘルパー
  const getOg = (prop) => {
    const pats = [
      new RegExp(`<meta[^>]+property=["']${prop}["'][^>]+content=["']([^"']*)["']`, 'i'),
      new RegExp(`<meta[^>]+content=["']([^"']*)["'][^>]+property=["']${prop}["']`, 'i'),
      new RegExp(`<meta[^>]+name=["']${prop}["'][^>]+content=["']([^"']*)["']`, 'i'),
    ];
    for (const p of pats) {
      const m = html.match(p);
      if (m) return m[1].replace(/&quot;/g,'"').replace(/&amp;/g,'&').replace(/&#39;/g,"'");
    }
    return '';
  };

  // X / Twitter
  if (/twitter\.com|x\.com/.test(url)) {
    const idMatch = url.match(/\/status\/(\d+)/);
    const postId  = idMatch ? idMatch[1] : hashStr(url);
    const title   = getOg('og:title') || '';
    const desc    = getOg('og:description') || '';
    const aMatch  = title.match(/^(.+?)\s+on\s+X:/i);
    return { source: 'x', postId, author: aMatch ? aMatch[1] : '', content: desc || title };
  }

  // note.com
  if (url.includes('note.com')) {
    const keyMatch  = url.match(/\/n\/([^/?#]+)/);
    const userMatch = url.match(/note\.com\/([^/]+)\//);
    const postId    = `note_${keyMatch ? keyMatch[1] : hashStr(url)}`;
    const title     = getOg('og:title') || '';
    const desc      = getOg('og:description') || '';
    const aMeta     = html.match(/<meta[^>]+name=["']author["'][^>]+content=["']([^"']*)["']/i);
    const author    = aMeta ? aMeta[1] : (userMatch ? `@${userMatch[1]}` : '');
    return { source: 'note', postId, author, content: `${title}\n\n${desc}`.trim() };
  }

  // 汎用
  const title  = getOg('og:title') || (html.match(/<title[^>]*>([^<]+)<\/title>/i)||[])[1] || '';
  const desc   = getOg('og:description') || '';
  const author = getOg('article:author') || '';
  return {
    source: 'web',
    postId: `web_${hashStr(url)}`,
    author,
    content: `${title}\n\n${desc}`.trim(),
  };
}

function hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) { h = Math.imul(31, h) + s.charCodeAt(i) | 0; }
  return Math.abs(h).toString(36).substring(0, 8);
}

// ── Anthropic API 呼び出し ────────────────────────────────────────
function callAnthropic(model, systemPrompt, userPrompt, maxTokens) {
  const key = getAnthropicKey();
  if (!key) throw new Error('ANTHROPIC_API_KEY が未設定です');

  const res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
    method: 'post',
    headers: {
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    payload: JSON.stringify({
      model, max_tokens: maxTokens,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
    }),
    muteHttpExceptions: true,
  });

  const json = JSON.parse(res.getContentText());
  if (json.error) throw new Error(json.error.message);
  return json.content[0].text;
}

function extractInsights(content, author, source) {
  const sys = `ビジネス系SNS分析の専門家として投稿から洞察をJSONで抽出してください。
{"themes":[],"key_insights":[],"audience_pain_points":[],"tone":""}の形式で。各配列5個以内。`;
  return callAnthropic(CLAUDE_HAIKU, sys, `著者: ${author}\n内容: ${content}`, 512);
}

function generateComments(author, content, url) {
  const sys = `あなたは実績ある経営者・起業家として数万フォロワーを持つXアカウントを運用しています。
ターゲット: 20〜40代の男性ビジネスマン・経営者・起業家

【バズる引用コメントの法則】
1. ファーストビューが命：最初の一文で「え？」「わかる」と掴む
2. 本質を突く：元投稿の「見えない真実」や「言えてない核心」を言語化する
3. 自分事化：読者が「自分のことだ」と感じる視点で書く
4. 強い意見を持つ：曖昧にせず立場を明確にする（断定調で）
5. 逆説・意外性：常識を覆すひと言を盛り込む
6. 感情を動かす：共感・驚き・軽い反論・保存欲を誘発する

【口調・スタイル】
- 断定調（〜だ、〜である、〜に尽きる）
- 体験・実感ベースの言葉
- 知的で鋭いが難しくない
- 綺麗事より本音

【禁止事項】
- ハッシュタグ・絵文字の多用
- 「〜ですね」「〜と思います」系の薄いコメント
- 当たり障りのない共感だけで終わる内容
- 140文字超え`;

  const prompt = `著者: ${author||'不明'}
元の投稿内容:
${content}
URL: ${url}

以下の形式で引用コメント5案を作成してください。
各案は140文字以内、ハッシュタグ・絵文字なし。断定調で。

**案1（共感・補足型）**
[元投稿の核心に「そうそう、さらに言うと〜」と一歩深めるコメント。読者が「わかる！」と感じる言語化]

**案2（問いかけ型）**
[読者が自分ごととして考え込む問いかけ。答えを押しつけず、脳に刺さる質問で終わる]

**案3（具体化型）**
[元投稿の抽象論を「つまり実際には〜」と具体的な場面・数字・事例で翻訳する]

**案4（反骨・逆説型）**
[「実はこれは逆で〜」「多くの人が勘違いしているのは〜」と常識を覆す視点を提示]

**案5（行動促進型）**
[「だから今すぐ〜」「明日から〜するだけで変わる」と読者の行動に直結させる]`;

  const raw = callAnthropic(CLAUDE_OPUS, sys, prompt, 2048);
  return parseComments(raw);
}

function parseComments(raw) {
  const comments = [], lines = raw.split('\n');
  let current = [], inComment = false;
  for (const line of lines) {
    const s = line.trim();
    if (s.startsWith('**案') && (s.includes('型') || s.includes('）'))) {
      if (current.length) { const c = current.join('\n').trim(); if (c) comments.push(c); current = []; }
      inComment = true;
      continue;
    }
    if (inComment && s) current.push(s);
  }
  if (current.length) { const c = current.join('\n').trim(); if (c) comments.push(c); }
  return comments.length >= 3 ? comments.slice(0, 5) : [raw];
}

function generateOriginalPosts(posts) {
  const sys = `あなたは実績ある経営者・起業家として数万フォロワーを持つXアカウントを運用しています。
ターゲット: 20〜40代の男性ビジネスマン・経営者・起業家

【バズるオリジナル投稿の法則】
1. 最初の1行で掴む：「え？」「わかる」「自分のこと？」と思わせる出だし
2. 本質を語る：表面的な話ではなく根本的な真実を言語化する
3. 具体性を入れる：「〇〇な人ほど〜」「〜した結果、気づいた」など実感のある言葉
4. 強い立場：「〜だと思います」ではなく「〜だ」と断言する
5. 読者を映す鏡：読んだ人が「自分のことだ」「誰かに送りたい」と感じる
6. 改行でリズムを作る：長文は改行で区切り、読みやすくする

【口調・スタイル】
- 断定調（〜だ、〜である、〜に尽きる）
- 体験・実感ベース（「〜年やって気づいた」「実際に〜した結果」）
- 知的だが難しくない、温かみのある鋭さ
- 偉そうにならず、でも芯はブレない

【バズりやすい型の活用】
- 真実型：「ほとんどの人が知らない〜」「〜の本当の理由」
- 対比型：「〇〇する人と△△する人の決定的な違い」
- 数字型：具体的な数字で驚きと信頼性を与える
- 問い型：読者に自己投影させる問いかけ
- 法則型：「〜の法則」でシェアされやすく記憶に残る

【禁止事項】
- ハッシュタグ・絵文字の多用
- 綺麗事・当たり障りのない言葉
- 「〜ですね」「〜と思います」系の弱い断言
- 140文字超え（改行込みで計算）`;

  const summary = posts.slice(0, 10).map(p => `[${p.source}] ${p.author}\n${String(p.content).substring(0, 150)}`).join('\n\n');
  const prompt  = `以下のコンテキストを経営者・起業家としての自分の経験と内面化した上で、
完全オリジナルのバズるツイートを5案生成してください。

【コンテキスト】
${summary}

【各型の狙いと条件】
- 真実型：「ほとんどの人が知らない〜」「〜の本当の理由は」など、常識を覆す真実を断言
- 対比型：「〇〇な人は〜、〇〇でない人は〜」成功者と非成功者・前後の対比で差を際立たせる
- 数字型：具体的な数字（期間・金額・割合・回数）を使い、信頼性と驚きを同時に与える
- 問い型：読者が「自分はどうだろう？」と考え込む問いかけ。答えを押しつけない
- 法則型：「〜の法則」「〜の原則」形式で記憶に残り、シェアされやすいフォーマット

形式（必ずこの形式で）:
**1. 真実型**
[ツイート本文]
テーマ: [テーマ]
**2. 対比型**
[ツイート本文]
テーマ: [テーマ]
**3. 数字型**
[ツイート本文]
テーマ: [テーマ]
**4. 問い型**
[ツイート本文]
テーマ: [テーマ]
**5. 法則型**
[ツイート本文]
テーマ: [テーマ]`;

  const raw = callAnthropic(CLAUDE_OPUS, sys, prompt, 2048);
  return parseOriginalPosts(raw);
}

function parseOriginalPosts(raw) {
  const posts = [], lines = raw.split('\n');
  let content = [], theme = '', inPost = false;
  for (const line of lines) {
    const s = line.trim();
    if (/^\*\*\d+\./.test(s)) {
      if (content.length) { posts.push({ content: content.join('\n').trim(), theme }); content = []; theme = ''; }
      inPost = true; continue;
    }
    if (s.startsWith('テーマ:') && inPost) { theme = s.replace('テーマ:', '').trim(); continue; }
    if (inPost && s) content.push(s);
  }
  if (content.length) posts.push({ content: content.join('\n').trim(), theme });
  return posts.length >= 2 ? posts.slice(0, 5) : [{ content: raw, theme: '' }];
}

// ── スプレッドシート操作 ──────────────────────────────────────────
function getSpreadsheet() {
  const id = getSpreadsheetId();
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
}

function getSheet(name) {
  const ss = getSpreadsheet();
  let sheet = ss.getSheetByName(name);
  if (!sheet) { sheet = ss.insertSheet(name); initSheetHeaders(sheet, name); }
  return sheet;
}

function initSheetHeaders(sheet, name) {
  const h = {
    posts:         ['id','source','post_id','author','content','url','like_count','quote_count','insights','collected_at','generated_at'],
    comments:      ['id','post_id','comment_number','comment','created_at'],
    original_posts:['id','post_number','content','theme','created_at'],
    pending_jobs:  ['id','type','data','destination','created_at','status'],
  };
  if (h[name]) { sheet.appendRow(h[name]); sheet.setFrozenRows(1); }
}

function getNextId(sheetName) {
  const sheet = getSheet(sheetName);
  const last  = sheet.getLastRow();
  if (last <= 1) return 1;
  const ids = sheet.getRange(2, 1, last - 1, 1).getValues().flat().filter(Number.isFinite);
  return ids.length ? Math.max(...ids) + 1 : 1;
}

function savePost(source, postId, author, content, url, likeCount, quoteCount) {
  const sheet = getSheet('posts');
  const data  = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][2]) === String(postId)) return data[i][0]; // 重複: 既存IDを返す
  }
  const id = getNextId('posts');
  sheet.appendRow([id, source, postId, author, content, url, likeCount||0, quoteCount||0, '', new Date().toISOString(), '']);
  return id;
}

function updatePostInsights(postId, insights) {
  const sheet = getSheet('posts'), data = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === postId) { sheet.getRange(i+1, 9).setValue(insights); return; }
  }
}

function saveComments(postId, comments) {
  const sheet = getSheet('comments');
  const data  = sheet.getDataRange().getValues();
  for (let i = data.length - 1; i >= 1; i--) {
    if (data[i][1] === postId) sheet.deleteRow(i + 1);
  }
  const now = new Date().toISOString();
  comments.forEach((c, i) => sheet.appendRow([getNextId('comments'), postId, i+1, c, now]));
  // generated_at 更新
  const ps = getSheet('posts'), pd = ps.getDataRange().getValues();
  for (let i = 1; i < pd.length; i++) {
    if (pd[i][0] === postId) { ps.getRange(i+1, 11).setValue(now); break; }
  }
}

function saveOriginalPosts(posts) {
  const sheet = getSheet('original_posts');
  if (sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
  const now = new Date().toISOString();
  posts.forEach((p, i) => sheet.appendRow([i+1, i+1, p.content, p.theme||'', now]));
}

function getPostById(id) {
  const data = getSheet('posts').getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === id) return { id:data[i][0], source:data[i][1], postId:data[i][2], author:data[i][3], content:data[i][4], url:data[i][5], generatedAt:data[i][10] };
  }
  return null;
}

function getPostsForContext(limit) {
  const data = getSheet('posts').getDataRange().getValues();
  if (data.length <= 1) return [];
  return data.slice(1).slice(-limit).map(r => ({ source:r[1], author:r[3], content:r[4], url:r[5], insights:r[8] }));
}

function countPosts() {
  const last = getSheet('posts').getLastRow();
  return Math.max(0, last - 1);
}

function getCommentsForPost(postId) {
  const data = getSheet('comments').getDataRange().getValues();
  return data.slice(1).filter(r => r[1] === postId).map(r => ({ number:r[2], comment:r[3] }));
}

function addPendingJob(type, data, dest) {
  getSheet('pending_jobs').appendRow([getNextId('pending_jobs'), type, data, dest, new Date().toISOString(), 'pending']);
}

// ── メッセージ構築 ────────────────────────────────────────────────
function buildListMessage() {
  const data = getSheet('posts').getDataRange().getValues();
  if (data.length <= 1) return '投稿がありません。URLを送信して追加してください。';
  const icons = { x:'𝕏', note:'📝', web:'🌐' };
  let msg = `📋 最近の投稿（${Math.min(data.length-1, 7)}件）\n\n`;
  data.slice(1).slice(-7).reverse().forEach(r => {
    const mark    = r[10] ? '✅' : '▪';
    const preview = String(r[4]).substring(0, 40).replace(/\n/g,' ');
    msg += `${mark} ID:${r[0]} ${icons[r[1]]||'📄'} ${preview}...\n`;
  });
  return msg + '\n詳細は「show <ID>」で確認できます';
}

function buildShowMessage(postId) {
  const post = getPostById(postId);
  if (!post) return `ID:${postId} の投稿が見つかりません。`;
  const icon = { x:'𝕏', note:'📝', web:'🌐' }[post.source] || '📄';
  let msg = `${icon} 投稿 ID:${postId}\n\n👤 ${post.author||'不明'}\n${String(post.content).substring(0,200)}\n🔗 ${post.url}`;
  const comments = getCommentsForPost(postId);
  if (!comments.length) return msg + `\n\nコメント未生成。「generate ${postId}」で生成できます。`;
  const labels = ['共感・補足型','問いかけ型','具体化型','反骨・逆説型','行動促進型'];
  msg += '\n\n💬 引用コメント\n\n';
  comments.forEach(c => { msg += `【案${c.number} ${labels[c.number-1]||''}】\n${c.comment}\n\n`; });
  return msg.trim();
}

function getHelpText() {
  return `📖 SNS Bot 使い方

URLを送信
→ 投稿を保存して引用コメント5案を生成

コマンド:
list → 最近の投稿を一覧表示
show <ID> → 投稿の詳細を表示
generate <ID> → コメントを再生成
original → オリジナルポストを生成
help → この使い方を表示`;
}

// ── LINE API ──────────────────────────────────────────────────────
function lineReply(replyToken, text) {
  const token = getLineToken();
  if (!token) return;
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    method: 'post',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    payload: JSON.stringify({ replyToken, messages: [{ type:'text', text: text.substring(0,4999) }] }),
    muteHttpExceptions: true,
  });
}

function linePush(dest, text) {
  const token = getLineToken();
  if (!token || !dest) return;
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/push', {
    method: 'post',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    payload: JSON.stringify({ to: dest, messages: [{ type:'text', text: text.substring(0,4999) }] }),
    muteHttpExceptions: true,
  });
}

function getDestination(source) {
  return source.groupId || source.roomId || source.userId || null;
}

// ── 初回セットアップ（手動で1回だけ実行） ─────────────────────────
function setup() {
  // シートを初期化
  ['posts', 'comments', 'original_posts', 'pending_jobs'].forEach(getSheet);

  // 1分ごとのトリガーを作成（重複防止）
  const existing = ScriptApp.getProjectTriggers();
  if (!existing.some(t => t.getHandlerFunction() === 'processPendingJobs')) {
    ScriptApp.newTrigger('processPendingJobs').timeBased().everyMinutes(1).create();
    Logger.log('✅ 1分トリガーを作成しました');
  } else {
    Logger.log('ℹ️ トリガーはすでに存在します');
  }

  Logger.log('✅ セットアップ完了！README.md の手順3以降を続けてください。');
}
