# SESSION 67 引き継ぎ（2026-08-18）

新しいチャットを開始したAIは、**このファイルと `README.md` を必ず最初に読むこと。**
ユーザー（岸本洋幸さん／HIRO）に同じ説明をさせないこと。

---

## 0. 最初に守るルール（絶対）

### セキュリティ

- **APIキー・トークン・シークレットの類を、チャットにもコードにも絶対に出力しない。**
  対象：`GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `SUPABASE_SERVICE_KEY` / `SUPABASE_KEY` /
  `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_TOKEN` /
  `CRON_TOKEN` / Apple の `.p8` 認証キーの中身 / パスワード全般。
- どうしても言及が必要なときは**必ずスクランブル（伏せ字）にする**。
  例：`AIza••••••••••••••••3f2a` / `sk_live_••••••••` / `-----BEGIN PRIVATE KEY----- ••• 省略 •••`
- キーは Cloud Run の環境変数と Supabase 側にのみ置く。**コードにも README にもベタ書きしない。**
- ユーザーがうっかりキーを貼ってしまった場合は、**その場で指摘し、ローテーション（再発行）を勧める。**
  以後の応答でそのキーを繰り返さない。
- SQL の結果や CSV を扱うときも、利用者名などの個人情報を不必要にチャットへ広げない。
  介護記録は要配慮個人情報を含む。

### ファイルの受け渡し（重要・この方法で滞りなく進む）

このセッションでは、ユーザーのMacのシェル（`device_bash`）が途中から起動しなくなった。
**AI側からファイルを読めない・git を実行できない場面がある。** そのときは次のどちらかを使う。

**① AIが必要なファイルを読みたいとき**
　→ **VSCodeのターミナルで実行するコマンドを提示し、ダウンロードフォルダへコピーさせる。**
　　ユーザーがそれをこのチャットに添付してくれる。この段取りをユーザーは了解済み。

```bash
# 例：AIが app.py と board.html を読みたいとき、こう投げる
cp "/Users/ZIMAX 1/dev/kaigo-ai-app/app.py" ~/Downloads/
cp "/Users/ZIMAX 1/dev/kaigo-ai-app/templates/board.html" ~/Downloads/
# 大きいファイルや一部だけでよいときは行を切り出す
sed -n '15080,15300p' "/Users/ZIMAX 1/dev/kaigo-ai-app/app.py" > ~/Downloads/app_board.txt
```

**② AIが修正したファイルを渡すとき**
　→ `SendUserFile` → `mcp__remote-devices__device_commit_files` で
　　`/Users/ZIMAX 1/dev/kaigo-ai-app/...` へ直接書き戻せる（`device_bash` が死んでいても動く）。
　　書き戻したあとの **git add / commit / push はユーザーに実行してもらう**（コマンドを丸ごと提示する）。

**git のロック残骸に注意。** AI側からコミットを試みて失敗すると
`.git/index.lock` `.git/HEAD.lock` が残り、ユーザー側の git が止まる。その場合はこれを先頭に付ける。

```bash
rm -f .git/index.lock .git/HEAD.lock
```

### ユーザーとの進め方

- 岸本さんはエンジニアではない。**一度に1タスク、5ステップ以内、具体的な操作手順で案内する。**
  過去に「情報量が多くて何からしていいのかわからなくなってきた」と言われている。
- **推測で断定しない。** 必ず根拠（DBの実データ・画面のスクリーンショット・ログ）を取ってから結論を言う。
  範囲を限定して調べたときは「この範囲では」と明示する。
- 現場（介護施設）が実際に使っている本番システム。**壊すと業務が止まる。**
- コミットメッセージの末尾には以下を付ける。

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

## 1. プロジェクトの基本

| 項目 | 内容 |
|---|---|
| プロダクト名 | **TASUKARU**（介護施設向けケース記録・バイタル管理システム） |
| リポジトリ | `cocokaraplus-max/kaigo-ai-app` |
| ローカルパス | `/Users/ZIMAX 1/dev/kaigo-ai-app/` |
| 開発ブランチ | `tasukaru-dev` → DEV に自動デプロイ（3〜5分） |
| 本番ブランチ | `tasukaru` → 本番に自動デプロイ（3〜5分） |
| DEV URL | `https://tasukaru-dev-191764727533.asia-northeast1.run.app` |
| 本番 URL | `https://tasukaru-191764727533.asia-northeast1.run.app` |
| 技術 | Python/Flask（`app.py` 約31,600行）, Supabase(Postgres+RLS), Cloud Run, Jinja2 |
| DEV Supabase | プロジェクト `otjevnmoycnvaxeltrtj`（facility_code: `DEMO001`） |
| 本番 Supabase | プロジェクト `abvglnkwtdeoaazyqwyd` |
| **本番の施設コード** | **`cocokaraplus-5526`** ← ここを間違えると調査が全部無駄になる |
| iOSアプリ | `/Users/ZIMAX 1/dev/tasukaru-app/`（Capacitor 8系） |
| Apple Team ID | `6AX82WT38B`（LIFE PLUS, LIMITED LIABILITY COMPANY・法人登録済み） |
| Bundle ID | `jp.lifeplus.tasukaru` |

**⚠️ 診断SQLを書く前に必ず施設コードを確認すること。**
過去に `cocokaraplus` で検索して「0件」を3回誤診し、ユーザーに無駄足を踏ませた。

### デプロイの流れ

```bash
# DEV へ
cd "/Users/ZIMAX 1/dev/kaigo-ai-app" && git add <files> && git commit -m "..." && git push origin tasukaru-dev
# 本番へ（DEVで検証してから）
cd "/Users/ZIMAX 1/dev/kaigo-ai-app" && git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru && git checkout tasukaru-dev
```

### 検証のやり方（有効だった手法）

Claude in Chrome でDEV/本番のページを開き、**ページのJSコンソールから直接 `fetch` して検証**する。
ログイン済みセッションが使えるので速い。テストデータは必ず後片付けすること。

```js
// 例：掲示板へテスト投稿して、表示されるかまで確認する
const fd=new FormData(); fd.append('content','DIAG-TEST');
fd.append('mention_names','[]'); fd.append('patient_names','[]');
fd.append('is_private','0'); fd.append('category_id','');
const r=await fetch('/api/board/create_post',{method:'POST',body:fd}); await r.json();
// 一覧の確認（/board?partial=1 は JSON。日本語は \uXXXX なので JSON.parse してから探す）
const j=await fetch('/board?partial=1').then(x=>x.json()); j.content.includes('DIAG-TEST');
// 後片付け
await fetch('/api/board/delete_post',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:<id>})});
```

---

## 2. このセッション（SESSION 67）でやったこと

### ① 再検査アラームの音を4種＋音なしから切替可能に（完了・本番反映済み）

- `templates/vitals.html` に `RC_SOUNDS`（A やさしいチャイム / B やわらかい二音 /
  C 患者モニター風 / D ナースコール風（既定） / 音なし）を定義。
  端末ごとに `localStorage['rc_alarm_sound']` へ保存（施設共通ではない）。
- UIは**アプリ内のみ**表示。画面上部の「🔔 通知を許可 / テスト」ボタンの下にプルダウン（`rc-alarm-panel`）。
- **Capacitor の `sound` は「アプリバンドル内のファイル名」**。
  - バンドルに無い名前を指定すると iOS は標準音も鳴らさず**完全に無音**（`sound:'default'` がこれで、7月からずっと壊れていた）
  - `sound` を渡さなければ**表示のみ・無音** ＝ 「音なし」設定はこれで実現
- 4つの `.wav` は `/Users/ZIMAX 1/dev/tasukaru-app/ios/App/App/` に置き、Xcodeのプロジェクトへ登録済み。
  実機で4音とも鳴ることを確認済み。
- `interruptionLevel:'timeSensitive'`（集中モード貫通）を設定。
  Xcodeで「Time Sensitive Notifications」capability が必要（**Appleへの申請は不要**）。
  消音（マナー）モードまで貫通するには `critical` が必要で、こちらは**Apple申請が必要**。

**Xcodeで .wav を追加するときの罠（再発しやすい）**
- `File → Add Files` のダイアログで Action が既定 **「Copy files to destination」**。
  同名ファイルが既にあると `alarm_chime 2.wav` のように**「 2」付き**でコピーされ、コード側と名前が合わず無音になる。
  → **「Reference files in place」** に変える。
- 同ダイアログの **Targets のチェックは既定で外れている**。外れたまま追加すると
  Copy Bundle Resources に入らず、やはり無音。
- Downloads など**リポジトリ外**のファイルを追加すると `project.pbxproj` に**絶対パス**で記録される。
  修正済み（`path = App/alarm_*.wav; sourceTree = "<group>"`）。バックアップ `project.pbxproj.bak_20260818`。
- Xcodeの **「Update to recommended settings」は実行しない**。
  `Enable User Script Sandboxing` が Capacitor のビルドスクリプトを壊すことがある。

### ② 掲示板に投稿できない（本番の重大障害・完了・本番反映済み）

現場から「投稿が全くできない。画像も何もかも。操作はできるが投稿されていない」と報告。
**別々の2つの不具合が同時に起きていた。**

**不具合A：空投稿（本命）**
`static/sw.js`（8/5更新）が非GETを `event.respondWith(fetch(event.request.clone()))` で**送り直していた**。
iOS（ホーム画面PWA/Safari）では、この送り直しで **multipart/form-data の body が丸ごと失われる**。
サーバでは `request.form`/`request.files` が空になり、
「投稿者名と時刻だけ・本文なし・カテゴリ未分類・画像なし」の空投稿が**保存に成功してしまう**。

- 修正 `sw-post-passthrough-v1`：**オンライン時は SW が非GETに一切介入しない。**
  オフライン時のみ `/api/*` と `/input` をキューに積む。`CACHE_VERSION` を v31 → **v32**。
- 保険 `board-empty-post-guard-v1`：`api_board_create_post` で本文・画像・音声・PDFが
  **すべて空**なら保存せず **400** を返す。Cloud Runログに `[board] empty post blocked ...` を出す。

**不具合B：誰にも見えない投稿（41件）**
公開範囲「メンションのみ」を選んで宛先を1人も選ばずに投稿すると
`is_private=true` / `mention_names=[]` になる。`/board` の可視判定は
`my_name in mention_names or staff_name == my_name` なので、**投稿者本人しか見えない**投稿が成立していた。
**影響は41件、最古は id 67（2026年春頃）。数ヶ月前から続いていた。**

- 修正 `board-empty-mention-fix-v1`：
  - `app.py`：`is_private and not mentions` なら `is_private = False` に倒す
  - `templates/board.html`：投稿前に確認ダイアログ／`openPostModal()` で毎回「全員に公開」へリセット
- 既存データは復旧済み（41件を `is_private=false` に更新。ユーザー判断で**全件表示のまま維持**）

### ③ 掲示板ヘッダーの表示崩れ（完了・本番反映済み）

- `board-sticky-safearea-v2/v3`：`box-shadow: 0 -200px 0` は
  **「200px上にずらした同形の影」**なので要素の高さぶんしか描かれず、影と要素の間に隙間ができて投稿が透けた。
  → `::before`（`bottom:100%; height:300px`）で上を丸ごと塗りつぶす方式に変更。
- 一度 margin/padding に `env(safe-area-inset-top)` を足したらヘッダーが約60px下がりすぎたため、
  **位置は元のまま**に戻した（v3）。

---

## 3. 次にやること（優先順）

### 【最優先】カレンダーの予定を、アプリを閉じていても通知する

ユーザーの要望：**「カレンダーで予定を入れたものを、今日の予定としてTASUKARUを閉じていても表示したい」**
「アラームと通知の仕組みをカレンダーにも実装したい」「音なしにもできるようにしたい」。

再検査アラームと同じ **Capacitor のローカル通知**で実現できる。
**Appleへの申請もAPNsも不要**（事前にiOSへ予約するので、アプリを閉じていても鳴る）。

**調査済みの現状（これを前提に設計してよい）**

| 項目 | 現状 |
|---|---|
| テンプレート | `templates/calendar.html`（2,113行）のみ |
| テーブル | `calendar_events` / `calendars` / `calendar_members` |
| `calendar_events` の列 | `id, facility_code, calendar_id, title, event_date, end_date, start_time, end_time, all_day, color, sticker, memo, repeat_type, repeat_until, notify_before, created_by, created_at, record_id` |
| 日時の持ち方 | **日付と時刻が別カラム**（`start_datetime` は無い）。複数日は**1日1行** |
| 範囲取得API | `GET /api/calendar_events?from=&to=`（`app.py:7348`）。**facility_code のみで絞る**（カレンダー単位の絞り込みはクライアント側 `getFilteredEvents()`） |
| 保存API | `POST /api/save_calendar_event`（`app.py:6898`） |
| 担当者 | **イベントに担当者列は無い。** 割り当ては「カレンダー単位」（`calendars.owner_name` + `calendar_members.staff_name` + `is_shared`） |
| 通知 | `notify_before`（0/10/30/60/1440分前）が**保存されているだけで、誰も読んでいない。送信処理は存在しない** |
| 繰り返し | **DBに未来の行は無い。** `repeat_type`/`repeat_until` からクライアントが仮想展開（`__calcRepeatOccurrences()`）。サーバ側で「今日の予定」を出すならこの展開を再現する必要がある |
| TOPページ | 「今日の予定」は**存在しない**（タスクの期限一覧のみ）。新規実装になる |

**実装の勘所**
- 既存の `templates/vitals.html` の `nativeScheduleRecheck` / `_rcLN()` / `_rcNotifId()` /
  `RC_SOUNDS` / `_rcSound()` が**そのまま手本になる**。音の切替（音なし含む）も同じ仕組みを流用する。
- **iOSの保留中ローカル通知は1アプリ64件が上限。** 全予定を無条件に予約すると溢れる。
  「今日＋明日ぶんだけ」「自分に関係するカレンダーだけ」など絞る設計にすること。
- 通知の予約はアプリを開いたときに同期する（再検査と同じ `checkRecheckAlarms()` 相当のポーリング）。
  **他端末で今日追加された予定は、その端末でアプリを開くまで予約されない**点をユーザーに説明すること。
- 「今日の予定」の画面表示（TOPページ等）も要望に含まれている。通知とセットで設計する。
- 音なしは `sound` キー自体を付けない。

**着手前にユーザーへ確認すべきこと**
1. 通知するのは「自分が見えるカレンダーの予定」全部か、特定カレンダーだけか
2. 通知のタイミングは既存の `notify_before`（10分前など）をそのまま使うか、朝まとめてか
3. 「今日の予定」をどこに出すか（TOPページ／カレンダー画面の上部／両方）

### 【現場対応・未完了】

- **現場の全端末でアプリを完全終了→再起動してもらう。** SWは古いものが残るとv32に入れ替わらない。
  （岸本さんに周知を依頼済み。実施できたか次のチャットで確認すること）
- 復旧した41件が全員に未読として出る。「全て既読にする」ボタンで整理できる旨も伝達済み。

### 【残タスク】

1. **利用者書類OCR**の実書類テスト（居宅サービス計画書・利用者情報シート）。
   ダミーでは合格済み（`sheet-ocr-v3`：転記の言い換え禁止、空欄は空欄のまま、ICF付箋16件正解）。
   API: `/api/patient-hub/sheet-ocr`（最大8枚）。
2. **Stripe Webhook の本番登録**
   - URL: `https://tasukaru-191764727533.asia-northeast1.run.app/api/stripe/webhook`
   - イベント: `checkout.session.completed` / `invoice.paid` / `customer.subscription.deleted`
   - 発行された署名シークレットを Cloud Run（サービス `tasukaru`）の環境変数
     `STRIPE_WEBHOOK_SECRET` に設定。**値はチャットに出さない。**
3. **Cloud Scheduler の `CRON_TOKEN`**：毎日9:00 JST に POST。
   トークンは**ヘッダー `X-Cron-Token` で渡す。URLには絶対に入れない。**
4. **`PLAN_ENFORCE = True`**（`app.py:2993` 付近）：他施設へ販売する直前まで `False` のままでよい。
5. **Apple / APNs**：App ID 登録 + Push Notifications capability 有効化 → `.p8` 認証キー発行。
   **`.p8` は1度しかダウンロードできない。中身は絶対にチャットへ貼らせない。**
   （※カレンダー通知はローカル通知で足りるので、APNsは急がない）
6. Android の内部テスト配布
7. `disaster.html` の「同期について」の記述が古い
8. 勤務予定の本人制限を一般職員アカウントで検証
9. リポジトリ整理（`templates/*.bak.*` が大量、`_to_delete/` の中身、
   `patient_visit_days` の孤児9行＝無害・読まれていない）

---

## 4. 効いた教訓（同じ失敗を繰り返さない）

- **欠番はバグの痕跡。** `board_posts` の id 342〜348 が欠けていたのは「壊れた投稿を現場が消した跡」だった。
  最初これを見落として「保存は正常」と誤診した。
- **画面のスクリーンショット1枚が最速。** 「名前だけ・未分類・本文なし」の1枚で
  「サーバに届いた時点で中身が空」と確定できた。推測を重ねる前に画面をもらう。
- **範囲を限定して調べたら、結論にも範囲を書く。** 「2件です」と言って実際は41件だった。
- **`box-shadow: 0 -Npx 0` は上を塗りつぶす手段ではない。** 塗りたいなら擬似要素を使う。
- **`/board?partial=1` はJSONで返る。** 日本語は `\uXXXX` エスケープなので、
  `JSON.parse` してから検索すること（生テキストを日本語で grep しても当たらない）。
- **`utils.py` の画像・音声・PDFアップロードは例外を握りつぶして空を返す**
  （`upload_images_to_supabase` 他）。ストレージ障害が「成功したが添付なし」に化けるので、
  添付が消える系の調査ではここを疑う。
