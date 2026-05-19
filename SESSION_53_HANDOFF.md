# TASUKARU 開発引き継ぎ — Session 53

---

## 📌 チャット冒頭に貼る文章

```
TASUKARUの開発を続けます。以下が現状です。

【リポジトリ】cocokaraplus-max/kaigo-ai-app
【ローカル】/Users/ZIMAX 1/dev/kaigo-ai-app/
【ブランチ】開発: tasukaru-dev / 本番: tasukaru
【dev URL】https://tasukaru-dev-191764727533.asia-northeast1.run.app
【本番URL】https://tasukaru-191764727533.asia-northeast1.run.app
【本番Supabase】abvglnkwtdeoaazyqwyd (facility_code: cocokaraplus-5526)
【dev Supabase】otjevnmoycnvaxeltrtj (facility_code: DEMO001)

【作業方式】
- Pythonスクリプトを ~/Desktop/ に置いて実行
- 必ずdev確認 → 本番マージの順番を厳守
- 本番マージ前に「本番にマージしてOKですか？」と必ず確認を取ること
- git add を忘れずに行うこと
- commitする前に必ず git branch で現在のブランチを確認すること

Session 52の引き継ぎファイルを読んで、残タスクから作業を開始してください。
引き継ぎファイル: /Users/ZIMAX 1/dev/kaigo-ai-app/SESSION_53_HANDOFF.md
```

---

## ⚠️ Session 52 の反省点

### 重大インシデント
1. **tasukaruブランチに直接commitしてしまうことが複数回発生**
   - 作業前に必ず `git branch` でブランチ確認をすること
   - commitはtasukaru-devのみ、本番はmergeのみ

---

## ✅ Session 52 完了済み修正（本番反映済み）

### calendar.html
- カレンダー作成モーダルのpadding-bottom修正（保存ボタン見切れ解消）
- 削除イベントのエラーハンドリング改善（alertでエラー表示）

### assessment.html
- 評価ページ：文字起こし結果（source_data）の保存対応
- AI生成ボタン追加（元データ欄の下）
- evalCollectFormData に source_data 追加
- evalResetForm で source_data クリア
- evalLoadEvaluation で source_data 復元

### app.py
- `/api/evaluation/ai_fill` エンドポイント追加
  - PT/OT/柔整視点でケアマネ向け報告文生成
  - ハルシネーション禁止プロンプト
- `/api/mark_all_read` エンドポイント追加（掲示板+ケース記録一括既読）
- 休み連絡カレンダー連動：
  - `_get_or_create_system_calendar()` ヘルパー追加
  - 休み連絡保存時にカレンダー自動登録
  - カレンダーイベント削除時にケース記録も削除
  - カレンダーイベント更新時にケース記録の日付も更新
  - is_systemカレンダーの削除禁止

### evaluation_helper.py
- ALLOWED_UPSERT_KEYS に `source_data` 追加

### daily_view.html
- 付箋ボタンを左端に移動・色改善（#ff6f00、背景#fff3e0）
- ページ遷移時 overflow リセット（メニューロック修正）
- TTS Audio要素方式に変更（iOS対応）
- _ttsUnlockAudio() 削除（iOS再生ブロック解消）
- 一括読み上げ：生成中でも押せる、生成完了次第再生
- FABをサイドドロワーに完全置き換え
  - 右端にピンクの3点タブ
  - タップでアイコン+ラベルのドロワーが開く
  - 検索・全て開く/閉じる・TOPへ
- 全既読ボタン（dvMarkAllRead）をページタイトル右端に追加

### board.html
- 全既読ボタンをタイトルバー右端に追加（案Cスタイル）
- boardMarkAllRead関数追加（/api/board/mark_all_read使用）
- sticky-stack外にボタン配置（z-index問題回避）

### base.html
- body/page-wrapper に overflow-x: hidden 追加（横ズレ修正）
- PC可変幅リサイズハンドル追加（ドラッグで幅変更、ダブルクリックでリセット）
- spaNav/navigateTo で body.overflow リセット
- updateMarkAllReadBar 関数（ページ別ボタン制御）
- markAllRead 関数

### admin.html
- html, body に overflow-x: hidden 追加
- savePatientProfileEdit に facility_code 追加

### input.html
- 休み連絡カテゴリ選択時に「休み期間」日付入力欄を表示
- 開始日・終了日（複数日対応）
- カレンダーに自動登録される旨の説明文

---

## 🗄️ DBマイグレーション（実施済み - dev + prod両方）

```sql
-- patient_evaluations
ALTER TABLE patient_evaluations ADD COLUMN IF NOT EXISTS source_data TEXT DEFAULT '';

-- records
ALTER TABLE records ADD COLUMN IF NOT EXISTS calendar_event_id BIGINT DEFAULT NULL;

-- calendars
ALTER TABLE calendars ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE;

-- patient_profiles（本番のみ不足していたカラムを追加）
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS care_manager_name TEXT DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS delegate_office TEXT DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS postal_code TEXT DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS certification_start_date DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS certification_end_date DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS long_goal_period_from DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS long_goal_period_to DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS short_goal_period_from DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS short_goal_period_to DATE DEFAULT NULL;
ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT NULL;
```

---

## 🔴 残タスク（Session 53 以降）

### 優先度：高

#### 1. カレンダー削除連動の動作確認
- **現状**: devでalertが出るようにしたが、実際のエラー内容未確認
- **要確認**: 削除ボタン押下後にalertに何が表示されるか
- **関連ファイル**: `templates/calendar.html`、`app.py`

#### 2. モニタリング生成の「今日は」→日付変換
- **要望**: ケース記録内の「今日は」「本日は」→`created_at`の日付に変換してからAI生成
- **関連**: `app.py` `/api/generate_monitoring` の `BASE_PROMPT` 付近
- **実装方針**: records取得時にcontent内の「今日は」「本日は」をX月X日はに前処理

#### 3. 評価ページ音声入力の保存問題（Session 51引き継ぎ）
- source_dataの保存は実装済み
- 保存が正常に動作しているか現場確認が必要

### 優先度：中

#### 4. admin.html 利用者検索機能の確認
- 「名前・カナ・番号で絞り込み」が正常に機能しているか確認・修正

#### 5. AI読み上げ生成後の自動再生（iOS制約）
- 現状: Audio要素方式に変更済み、個別・一括ともに動作確認済み
- 一括読み上げは生成中でも押せるようになった

### 優先度：低

#### 6. 保留タスク（Session 50以前）
- A. 目標管理の利用者情報紐付け
- B. バイタル入力改修4項目
- C. PC専用一括入力画面
- D. 方式B（サーバーPDF生成）

---

## 🔧 重要な技術的知見

### ブランチ管理
- **必ずtasukaru-devで作業**
- commitの前に `git branch` で確認
- 本番へは `git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru`

### iOS Audio制約
- AudioContext方式はfetchのthen()内では動かない
- 解決策: `new Audio()`をタップ時に先に作成、srcは後から差し替え
- `_ttsUnlockAudio()`は不要になった（むしろ邪魔）

### カレンダー連動
- `records.calendar_event_id` でカレンダーイベントと紐付け
- `calendars.is_system = True` のカレンダーは削除不可
- 「TASUKARUケース記録連動」カテゴリは自動作成

### Supabase直接アクセス（admin.html）
- patient_profilesはSupabaseに直接PATCH
- `facility_code`を必ずpayloadに含める（RLS対策）
- カラム名はDBと完全一致が必要

### PC可変幅
- CSS変数 `--page-max-width` で制御
- `localStorage`に保存、ダブルクリックで480pxリセット
- PCのみ表示（768px以上）

---

## 📁 今回変更したファイル

```
templates/
  admin.html          ← facility_code修正、overflow-x
  assessment.html     ← source_data保存、AI生成ボタン
  base.html           ← overflow修正、PC可変幅、全既読JS
  board.html          ← 全既読ボタン、boardMarkAllRead
  calendar.html       ← padding修正、削除エラーハンドリング
  daily_view.html     ← 付箋、TTS、FAB→サイドドロワー、全既読
  input.html          ← 休み連絡日付入力欄

app.py                ← ai_fill、mark_all_read、カレンダー連動
evaluation_helper.py  ← source_data追加
```
