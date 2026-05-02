# 🚨 Session 11 引き継ぎ書(2026-05-03 作成) — Step 2 全工程完了 / Step 3・4 未着手

## ⚠️ 最重要: 必ず最初に読むこと

このドキュメントは Session 11(再検査アラーム機能 Step 2-② / Step 2-③ 実装完了)を
新しいClaudeに完全に引き継ぐためのものです。**勝手に仕様や実装方針を変更すると大事故** になります。
必ず以下を厳守してください。

---

## 📋 プロジェクト基本情報(変更不可)

- リポジトリ: https://github.com/cocokaraplus-max/kaigo-ai-app
- ブランチ: `tasukaru-dev`
- dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
- prod URL: https://tasukaru-191764727533.asia-northeast1.run.app
- Mac作業パス: `~/dev/kaigo-ai-app`(ユーザー名 `ZIMAX 1` にスペースあり、注意)
- ファイル受け渡し場所: **`~/Desktop/`**(本人はDesktopに統一済み、Downloadsではない)
- Supabaseダッシュボード: https://supabase.com/dashboard/project/otjevnmoycnvaxeltrtj/sql

---

## 🔥 引き継ぎ書の絶対厳守事項(教訓1〜12)

1. **マニュアル上部のフワフワ動くタスカルくんは絶対に削除・変更しない**
2. **admin_settingsへのupsert(on_conflict)禁止** → 42P10エラー発生
3. **新規Supabaseテーブル作成時はRLS必ずDISABLE**(silent failure防止) — Session 11でこれを忘れて再発した(後述)
4. **JS編集時はブレースバランスチェック必須**(`{` と `}` の数を python3 で計測)
5. **コミットメッセージで日本語半角括弧()禁止、英字シンプル**
6. **iPhone Safariキャッシュは強い、`?cb=YYYYMMDDx` 必須**
7. **ファイル置換時は配置直後に必ず `wc -l` / `ls -la` / `grep -c` で検証**
8. **PWA Service Workerが古いコード配信の元凶**(ブラウザDev toolsからunregister手順を案内)
9. **patient_visit_days.patient_id=text型、patients.id=bigint型 → 常に str() 化**
10. **`.alert` クラス名はグローバル予約済み**(base.htmlで `display:flex`)。代わりに `is-alert` を使う
11. **【新】CSSクラス名の衝突に注意** — Session 11 で `recheck-time-input` クラスが既存の「設定タブ通知時刻UI」と衝突しかけた。新規追加は別プレフィックス推奨(例: `schedule-time-input`)
12. **【新】チャットからのファイルDLは Desktop に届く** — Downloadsにはない。`ls -la ~/Desktop/` で確認すること
13. **【新】コマンドコピペ時のマークダウン化問題** — チャット中の `app.py` がリンク化されて `[app.py](http://app.py)` としてターミナルに貼り付くことがある。コードブロック内テキストを直接選択するよう案内する。`grep`の出力で `UID:[xxx@yyy.app](mailto:xxx@yyy.app)` のように表示されるのは **ターミナル側の自動リンク化表示で実ファイルは正常**(hexdumpで確認可能)

---

## ✅ 完了済み実装(変更しない、push済み)

### Step 8 完了分(過去セッション)
- 曜日表示の一体化、利用者管理モーダル、削除2択ダイアログ、vital_daily_excludesテーブル等
- 履歴UI改修(月切替 + Chart.js折れ線グラフ + 1日複数測定スワイプ)
- 旧データ統合SQL実行(D025等の非数値patient_idを数値IDに統合、計53通り)

### Step 9 完了分(Session 9)
- `/api/add_vital`, `/api/update_vital`, `/api/delete_vital` 追加
- 共通エディタコンテナ(`daily-editor-container`)
- C案タブ式エディタ(時刻ピル + 「+追加」)
- タブ名変更:「記録」→「測定」、「全員確認」→「本日の記録」
- 押されたページの測定がデフォルト選択

### Step 1 完了分(Session 9〜10、コミット 8803c33)
- `hasAnyAlert(v) || v.recheck === true` のOR判定(2箇所)
- エディタフォームに「⚠ 再検査が必要(手動)」オレンジチェックボックス追加
- 保存時 自動 OR 手動 で recheck=true
- 保存メッセージ分岐(異常値検出/手動マーク/通常)

### Step 2-① 完了分(Session 10、コミット 8441073)
- Supabase: `vital_recheck_schedules` テーブル作成済
- app.py: 4つの新API追加(post/get/complete/delete)

### Step 2-② 完了分(Session 11、コミット 3ee08a3 + 4ccd76b)
- 全員確認(本日の記録)タブのアコーディオン編集パネル内に再検査スケジューラ追加
- クイックボタン4つ:+15分 / +30分 / +1時間 / +2時間
- 直接時刻入力 + メモ欄(異常値時に自動プリフィル「血圧:200/140」など)
- 「📅 リマインダーに登録」→ サーバー保存 + .ics 自動ダウンロード
- 既存予約一覧表示(時刻 / 相対時刻「45分後」/ メモ / 完了・削除ボタン)
- 過去時刻チェック(過去5分以上前なら確認ダイアログ)
- **新規追加モード時は再検査セクション非表示**(意図的)
- **CSSクラス名衝突回避**: 私の追加分は `schedule-time-input` / `schedule-time-row` を使用(既存の `recheck-time-input` は別機能なので触らない)
- **.icsファイル名はASCII化**: `recheck-{patient_id}-{YYYYMMDD-HHMM}.ics` 形式(macOSで日本語ファイル名が化ける問題を回避)

### Step 2-③ 完了分(Session 11、コミット 8611db5)
- app.py: `/api/recheck_schedule/snooze` POSTエンドポイント追加(scheduled_at を N分後に更新)
- 30秒間隔のポーリング(本日の記録タブ表示中のみ起動、他タブで停止)
- 期限切れ検出(`scheduled_at <= now()` かつ未発火IDのみ)
- アラームモーダル(赤枠+パルスアニメーション、画面中央表示)
- Web Audio APIでビープ音(880Hz/660Hz, 4音、計0.9秒)
  - **ユーザーがクリック/タップしてからでないと音は出ない**(ブラウザのautoplay制限)
- 3つのアクション:
  - 「今から測定する」→ 該当利用者のエディタを自動展開
  - 「10分後に再通知」→ snooze API呼び出し、scheduled_atを今+10分に更新
  - 「完了にする」→ complete API呼び出し
- 同一予約の連続発火防止(`_alarmFiredIds` Set で発火済み管理)
- ポーリング中はモーダル表示中だと停止(重複防止)
- ページ離脱時にポーリングクリア

### push済みコミット(最新順、2026-05-03 01:00時点)
```
8611db5 (HEAD -> tasukaru-dev, origin/tasukaru-dev) feat vitals recheck alarm with polling beep modal and snooze api  [Step 2-③]
4ccd76b fix vitals recheck ics filename ascii safe with patient id and timestamp  [Step 2-② フォロー]
3ee08a3 feat vitals recheck schedule ui with quick buttons and ics download  [Step 2-② 本体]
8441073 feat vital recheck schedule apis post get complete delete  [Step 2-①]
8803c33 fix vitals manual recheck reflect in display and add manual checkbox in editor  [Step 1]
8bfc5a9 docs vital alarm step plan and android device behavior and guide page
0503408 docs vital alarm step plan and android device behavior
61e84e5 feat vitals shared editor container accessible from all pages
8d45517 fix vitals daily table is-alert class to avoid global alert flex
```

---

## 🚨 Session 11 で発生した重大インシデント(教訓記録)

### インシデント1: ファイルDL先の食い違い
- ユーザーは Desktop にDLする習慣だが、Claudeは最初 Downloads を案内した
- ユーザーが古い `~/Downloads/vitals.html`(5/1 21:27 のSession 9 以前のもの)を `templates/` に上書きしてしまい、Step 1 の機能(`ef-recheck`, `manual-recheck-label`)が一時的に消滅
- **教訓: ファイル受け渡しは必ず Desktop パスを案内、DL前に必ず古いファイル削除を指示、`ls -la` で日付確認を強制**
- 復旧方法: `git checkout templates/vitals.html` で直前コミット状態に戻せた(まだコミットしていなかったので無事)

### インシデント2: Supabase RLS 無効化漏れ
- 引き継ぎ書には「RLS無効化済」と記載があったが、実際には有効のままだった
- ブラウザで「📅 リマインダーに登録」を押すと `42501 row-level security policy` エラー
- ユーザーに以下のSQLを実行してもらって解決:
  ```sql
  ALTER TABLE vital_recheck_schedules DISABLE ROW LEVEL SECURITY;
  ```
- **教訓: 教訓3 を再強調。Supabase テーブル作成時は必ず RLS DISABLE を確認**
- ユーザー側で `SELECT rowsecurity FROM pg_tables WHERE tablename='vital_recheck_schedules'` で確認済み(false)

### インシデント3: コミット忘れ
- 「fix vitals recheck ics filename」修正時、ユーザーが `it add` (typo) → `git commit` (空ステージング) → `git push` (Everything up-to-date)で進んでしまった
- **教訓: コミット前後で `git status` 確認を必ず案内する。ハッシュが進んでいるかを `git log --oneline` で確認**

---

## 🎯 Step 2-③ の動作確認状況(2026-05-03 01:00)

**push済み・Cloud Run デプロイ済(と思われる)** だが、ユーザーは深夜のためここまでで一旦終了。
動作確認は次セッションで実施予定。

### 動作確認手順(次セッションで案内する)

1. dev環境を `?cb=20260503b` 付きで開く:
   ```
   https://tasukaru-dev-191764727533.asia-northeast1.run.app/vitals?cb=20260503b
   ```
2. (キャッシュ頑固な場合) Chrome DevTools → Application → Service Workers → "Unregister" + Storage → "Clear site data"
3. 「本日の記録」タブを開く
4. **テスト用に過去時刻の予約を作成**:
   - 異常値のある利用者の編集を開く(例: 池田 ヨシ patient_id=23)
   - 「直接時刻」を数分前に設定
   - 「過去時刻ですが本当に登録しますか?」→「OK」
5. **30秒以内にアラーム発火**するはず:
   - 🔴 赤い枠でパルス表示のモーダル
   - ピポピポ音
   - 3つのボタンが選べる

### Step 2-③ 動作確認チェックリスト
- [ ] モーダル表示
- [ ] ビープ音(マナーモードでも音が出るはずだが、ブラウザ音量に依存)
- [ ] 「今から測定する」→ エディタが開く
- [ ] 「10分後に再通知」→ 予約一覧の時刻が10分後にずれる
- [ ] 「完了にする」→ 予約が完了状態に
- [ ] 別タブに切り替えて戻ってもポーリングが動く

---

## 🎯 アラーム機能の意思決定(確定済み・絶対変更禁止)

### ユーザーの確定要望(再掲)
1. **手動「再検査必要」ボタンも残す** — 閾値内でも職員判断で再検査指示できる
2. **自動再検査マークも併存** — 異常値検出で自動表示
3. **再検査時刻指定**: 「30分後」ボタン + 直接時刻入力 **両方** 提供
4. **アラーム鳴動条件**:
   - **画面スリープ中も鳴る**(超重要、これは Step 3 の Push通知 か .ics でしか実現できない)
   - 別アプリ使用中も鳴る
   - アプリ閉じてても鳴る
5. **画面アラーム形式**: 音 + 画面ダイアログで「誰の再検査か」明示
6. **介護現場の運用**: 「アプリは開いてない事が多い」

### 採用方式: 「C案」段階的実装(全工程の進捗)

| 段階 | 内容 | 工数 | 費用 | 状況 |
|------|------|------|------|------|
| Step 1 | 手動再検査ボタンの表示反映バグ修正 | 15分 | 無料 | ✅ 完了 |
| Step 2-① | DBテーブル + API追加 | 30分 | 無料 | ✅ 完了 |
| Step 2-② | UI実装(再検査時刻設定 + .icsダウンロード) | 1〜2時間 | 無料 | ✅ 完了 |
| Step 2-③ | アプリ内アラーム(画面開いてる時、音+ダイアログ) | 1時間 | 無料 | ✅ 完了(動作確認待ち) |
| **Step 3** | **Firebase Push通知で完全自動化** | **半日〜1日** | **無料** | **⏸ 運用後判断(勝手に着手禁止)** |
| **Step 4** | **利用者向けガイドページ** | **-** | **無料** | **⏸ Step 2 完了後必須** |

### 却下した選択肢(蒸し返し禁止)

| 却下案 | 却下理由 |
|--------|----------|
| Web Audio APIのみ | スリープ中鳴らない(→ Step 2-③ はあくまで補助、メインは .ics) |
| ブラウザ通知(Notification API) | iOS Safariで音鳴らず |
| 専用ネイティブアプリ化 | 工数膨大、ストア審査必要 |
| 完全自動化を最初から(Bを直接) | 工数大きい→運用後に拡張判断したい |

### 端末動作の確定情報
- iPhone/Android両方で .icsリマインダーは確実に鳴る(スリープ中も)
- Android Doze modeでもカレンダーアラームはホワイトリスト
- Xiaomi/HUAWEI:カレンダーアプリを「電池最適化対象外」に設定が必要
- iOS/Android仕様上、自動カレンダー登録は禁止 → 「📅登録」1タップは仕様

### 費用
- **完全無料で実装可能**(Firebase Sparkプランも無料、メッセージ無制限、クレカ登録不要)
- ユーザーは「お金がかかる」ことを警戒している → 無料であることを明示する

---

## ⏸ Step 3 未着手 [運用後判断]

Firebase Push通知。**ユーザーが「使ってみて必要なら」と判断保留**。
**勝手に着手禁止**。Step 2-③ の運用フィードバックを得てから判断を仰ぐ。

主要タスク(着手時のメモ):
- VAPID鍵生成、Service Worker拡張、FCMトークン管理、サーバー側push送信
- iOS:PWA化必須(ホーム画面追加)
- DBに `fcm_subscriptions` テーブル追加予定
- Firebase Sparkプラン(無料)で実装可能

---

## ⏸ Step 4 未着手 [Step 2 完了後必須・最優先候補]

**Step 2 が完了したので、次セッションでは Step 4 が最優先候補**。

利用者向けガイドページ。設定タブの中に「📚 使い方ガイド」セクション追加。
- iOS版設定手順(画像付き推奨)
- Android版設定手順(Xiaomi/HUAWEI注意点含む)
- トラブルシューティング(アラーム鳴らない時)
- 「いつ・どこで通知が鳴るのか」一覧表
- .icsの登録方法、カレンダーアプリ毎の動作

詳細は **既存の README.md(L998まで) 内に記載済み**。新セッションで作業前に必ず読むこと。

---

## 📐 動作確認用データ

### Demo環境
- facility_code: `DEMO001`
- 石川 トメ: patients.id=25, weekdays='5'
- 池田 ヨシ: patients.id=23, 5/2 に複数測定あり(11:24、05:55、05:59 全て異常値)
- patient_visit_days/vitals 共通でpatient_idはstr型として扱う

### Chrome連携で利用可能なツール
Claude in Chrome MCP: tabs_context_mcp/javascript_tool/computer/browser_batch/navigate等

新セッションでは `tabs_context_mcp` で開いているタブを確認すること。

---

## 🚨 新セッション開始時のチェックリスト

新しいClaudeは以下を**必ず**実施してから作業を始める:

1. [ ] このドキュメントを最後まで読む
2. [ ] 必要なら `/mnt/transcripts/journal.txt` で過去セッション履歴を確認
3. [ ] ユーザーに現在の状況を確認(動作確認は済んだか、Step 4 に進むか、別の改修要望か)
4. [ ] git log でコミット状況を確認するようユーザーに依頼
5. [ ] Mac側のapp.pyとvitals.htmlの状況を確認するようユーザーに依頼:
   ```bash
   cd ~/dev/kaigo-ai-app
   wc -l app.py templates/vitals.html
   grep -c "def api_recheck_schedule" app.py     # 5 であるべき
   grep -c "snooze" app.py                       # 3 であるべき
   grep -c "ef-recheck" templates/vitals.html    # 2 であるべき
   grep -c "manual-recheck-label" templates/vitals.html  # 4 であるべき
   grep -c "saveRecheckSchedule" templates/vitals.html   # 2 であるべき
   grep -c "alarm-modal\|alarm-overlay" templates/vitals.html  # 23 であるべき
   ```
6. [ ] **ファイル受け渡しは Desktop パス案内(必ず古いファイル削除指示+日付確認)**
7. [ ] 仕様の蒸し返しを禁止(新提案や変更したくならないこと)
8. [ ] **コマンド案内時はコードブロック内のテキストを選択するよう必ず注意喚起**(マークダウン化問題)

---

## 💡 既知の注意事項(Session 11 で再確認)

### Service Workerのキャッシュ問題
push後にユーザーがブラウザを開いても古いコードが表示される場合:
```javascript
// Chrome連携で実行
(async () => {
  const rs = await navigator.serviceWorker.getRegistrations();
  for (const r of rs) await r.unregister();
  if (window.caches) {
    const names = await caches.keys();
    for (const n of names) await caches.delete(n);
  }
  return 'SWクリア';
})()
```
そして `?cb=YYYYMMDDx` 付きで再読み込み。

### Cloud Build ラグ
push後、Cloud Run にデプロイされるまで **約30秒〜1分** かかる。新セッションで「push したのに反映されない」と言われたら、まず30秒待ってから動作確認する。

### マークダウンリンク化問題(Session 11 で複数回発生)
- ユーザーがコマンドをコピペする時、マークダウンの自動リンク化で `[app.py](http://app.py)` のような形式になることがある
- ターミナルでも `UID:recheck-...@tasukaru.app` が `UID:[recheck-...@tasukaru.app](mailto:recheck-...@tasukaru.app)` と表示されるが、実ファイルは正常(hexdumpで確認可能)
- 対策: コードブロック内のテキストだけをコピーするよう案内する

### Web Audio APIのautoplay制限
- ブラウザはユーザー操作なしの音再生を制限
- アラーム音は、ユーザーがページ内で1度でもクリック/タップしていれば鳴る
- ログイン後のページ遷移自体がインタラクションになるので、通常は問題ない
- 鳴らない場合でもモーダルは確実に表示される

---

## 📦 ファイル状態(2026-05-03 01:00時点、新セッション開始時)

### Mac (~/dev/kaigo-ai-app)(push済み)
- `app.py`: **4383行 / 196216 bytes**(Step 2-③ snooze API追加済み)
- `templates/vitals.html`: **2980行 / 144326 bytes**(Step 2-③ アラーム機能追加済み)
- `README.md`: 998行(Session 9 引き継ぎ書追記済み、まだ Session 10/11 の追記はしていない)

### Cloud Run dev環境
- 上記コミット 8611db5 がデプロイ済み(のはず、要確認)

### Supabase
- `vital_recheck_schedules` テーブル作成済(**Session 11 で RLS DISABLE 確認済 → false**)
- `vital_daily_excludes` テーブル作成済(RLS無効化済)
- 旧データ統合 (D025等→数値ID) 完了済

---

## ✅ 新セッションへのバトン

このドキュメントを引き継ぎ、状況を確認してから次のアクションを決める。

**最初の発言例**:
> 「Session 11 引き継ぎを確認しました。Step 2(全工程 ①②③)まで完了し、現在は動作確認待ちの状態です。
> まず Mac とリポジトリの状態を確認させてください。その後、ご希望に応じて以下のいずれかに進められます:
> - Step 2-③ の動作確認のフォロー(まだなら)
> - Step 4(利用者向けガイドページ)に着手 ← Step 2 完了後必須なので推奨
> - その他の改修要望」

仕様や設計を勝手に変更しないこと。ユーザーが望んでいないこと(例:新しい機能追加、UI再設計、別の方式への変更)を提案しないこと。引き継ぎ書の指示通りに段階的に進めること。

特に Step 3(Firebase Push)は **ユーザーから明示的に着手依頼があるまで提案しない**。
