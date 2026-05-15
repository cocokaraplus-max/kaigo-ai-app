# TASUKARU 介護AI アプリ 開発引き継ぎドキュメント
**最終更新: Session 45（2026-05-16）**

---

## 🏗️ プロジェクト基本情報

| 項目 | 内容 |
|---|---|
| リポジトリ | `cocokaraplus-max/kaigo-ai-app` |
| 開発ブランチ | `tasukaru-dev` |
| 本番ブランチ | `tasukaru`（mainではない） |
| dev URL | `https://tasukaru-dev-191764727533.asia-northeast1.run.app` |
| 本番 URL | `https://tasukaru-191764727533.asia-northeast1.run.app` |
| 本番Supabase | project ID `abvglnkwtdeoaazyqwyd` |
| dev Supabase | project ID `otjevnmoycnvaxeltrtj` |
| デプロイ | pushから約2分でCloud Build自動デプロイ |
| Cloud Buildプロジェクト | `TASUKARU-production` |

---

## ✅ Session 44-45 完了項目

### 1. assessment.html — 音声入力UI刷新
- Web Speech API → MediaRecorder + Gemini に完全移行
- 独り言モード（`/api/transcribe`）と対面会話モード（`/api/evaluation/ingest_file?audio_mode=dialog`）のタブ切替
- 4状態UI：待機中 → 録音中 → 一時停止 ⇄ 再開 → 編集・確定
- コミット: `6268ef8`

### 2. input.html — 録音UIリニューアル
- 旧「手動AI文章化ボタン」→ 停止後自動Gemini文字起こし方式に
- 独り言モードのみ（対面会話不要）
- 写真アップロードエリアは**現行デザインのまま維持**（触らない）
- 「記録に追加する」で`content-area`に直接流し込み
- コミット: `a96ec03`

### 3. admin.html — まもる君CSVインポート修正
- BOM（`\uFEFF`）除去
- 半角カタカナ→ひらがな変換対応（`ｱｻﾐ`→`あさみ`）
- 和暦→西暦変換（`S15.1.28`→`1940-01-28`）
- ※ フロントエンドFileReader経由のCSV読み込みUIはPC/iPhoneとも動作しない問題あり → SQL直接投入で対応

### 4. 本番DB移行（Supabase: abvglnkwtdeoaazyqwyd）
- `patient_profiles`テーブル新規作成
- `patients`テーブルから79件コピー
- `patient_visit_days` / `vitals` / `vital_daily_excludes` / `vital_recheck_schedules` のpatient_id UUID更新
- まもる君CSV（利用者一覧１.csv）79件をSQL直接投入
- 重複データ整理（146件→81件）、氏名スペース統一
- ケアマネ・住所・介護度等のデータをpatient_numberで照合してUPDATE

### 5. base.html — 下部メニュー固定＋TOPスクロール設定
- `.bottom-nav`に`position: fixed`を追加（メニューが上下に動く問題を修正）
- `.page-wrapper`の`padding-bottom`を`5rem`に調整
- 設定モーダル（歯車アイコン）に「ページトップへ移動」トグルを追加
- localStorage（`tasukaru_nav_scroll_top`）で設定を保存
- コミット: `e4a234d`

### 6. コードを本番マージ済み
- `tasukaru-dev` → `tasukaru`へマージ完了

---

## ⚠️ 残課題・既知の問題

### 🔴 優先度高

#### モニタリング報告書の印刷機能（Session 45メイン予定）
- `templates/history.html` がモニタリングメニューの実体（注意！）
- `monitoring_integration.py` に機能実装
- 印刷レイアウト・帳票デザインの検討から始める

#### CSVインポートUIの根本修正
- フロントエンドのFileReader経由でCSV読み込みがPC/iPhoneとも動作しない
- `ondrop`も`onchange`も発火しない（原因不明）
- **推奨対応**：バックエンドAPI方式（`/api/import_csv`エンドポイント新規作成）に変更

#### カナの半角濁点が残っている
- `patient_profiles.user_name_kana`に「あへﾞ きみえ」のように半角濁点が混在
- Pythonの変換ロジックを修正してUPDATEが必要

### 🟡 優先度中

#### patient_id=75・77の重複データ整理
- `patient_visit_days`でchart_number=241が今井広子・板倉篠麿に重複
- この2件はpatient_visit_daysのUUID更新をスキップ済み
- 手動整理が必要

#### assessment.htmlとpatient_profilesの連動
- 利用者選択時に`patient_profiles`から介護度・長短期目標を自動セット

#### 第2弾：AI評価文生成
- 元データ（音声・写真・PDF）→ Gemini →「訓練による変化」「課題とその要因」
- `/api/evaluation/generate`エンドポイントを新規作成

### 🟢 優先度低

#### 検索のもたつき改善（記録入力）
- blur処理の300msタイムアウトを調整する余地あり

---

## 🏗️ アーキテクチャ現状

### DB（本番: abvglnkwtdeoaazyqwyd）

| テーブル | 状態 | 備考 |
|---|---|---|
| `patient_profiles` | ✅ 81件（本番運用中） | まもる君データ統合済み |
| `patients` | ⚠️ 残存 | 削除未実施・旧テーブル |
| `patient_visit_days` | ✅ UUID移行済み（76件/2件スキップ） | |
| `vitals` | ✅ UUID移行済み | |
| `vital_daily_excludes` | ✅ text型変換＋UUID移行済み | |
| `vital_recheck_schedules` | ✅ UUID移行済み | |

### 音声入力アーキテクチャ（確定）

| 画面 | 録音方式 | 文字起こし | 話者分離 |
|---|---|---|---|
| assessment.html | MediaRecorder | Gemini `/api/transcribe` | ✅ 対面会話モード |
| input.html | MediaRecorder | Gemini `/api/transcribe` | ❌ 独り言のみ |
| vitals.html | MediaRecorder | Gemini | ❌ バイタル抽出 |

### 重要ファイル

| ファイル | 役割 |
|---|---|
| `app.py` | Flaskメイン（6000行超） |
| `templates/base.html` | 共通レイアウト・下部ナビ・設定モーダル |
| `templates/assessment.html` | 月次評価（Session 44刷新） |
| `templates/history.html` | **モニタリングメニューの実体**（注意！） |
| `templates/input.html` | 記録入力（Session 44刷新） |
| `templates/admin.html` | 管理者メニュー（CSV修正済み） |
| `templates/patient_profile.html` | 利用者詳細情報（Session 43新規） |
| `templates/top.html` | TOPページ・設定モーダルJS |
| `monitoring_integration.py` | モニタリング機能（別ファイル） |

---

## 📋 作業の進め方（次のClaudeへ）

### 基本ルール
1. **本番データは慎重に** → SQLは必ず内容を提示してから実行確認を取る
2. **コードは段階的に確認** → デザイン変更はモックを先に見せてから実装
3. **デプロイ手順** → `tasukaru-dev`で開発→動作確認→`tasukaru`にマージ
4. **本番ブランチは`tasukaru`** → `main`ではない（間違えやすい）
5. **削除・上書きは特に慎重に** → 本番の実利用者データが入っている

### マージコマンド（毎回使う）
```bash
git stash && git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru && git checkout tasukaru-dev
```

### 開発→確認の流れ
1. `tasukaru-dev`ブランチで実装
2. `git push origin tasukaru-dev`（約2分でdev環境に自動デプロイ）
3. `https://tasukaru-dev-191764727533.asia-northeast1.run.app` で動作確認
4. OKなら上記マージコマンドで本番反映

### SQL実行の安全ルール
- **SELECT系** → 確認なしに実行OK
- **INSERT系** → 内容提示→確認→実行
- **UPDATE系** → 内容提示→確認→実行（特に慎重に）
- **DELETE系** → 内容提示→確認→「Run query」ダイアログが出たら再確認

### よく使うSupabase SQL Editor URL
- 本番: `https://supabase.com/dashboard/project/abvglnkwtdeoaazyqwyd/sql/new`
- dev: `https://supabase.com/dashboard/project/otjevnmoycnvaxeltrtj/sql/new`

---

## 🚀 次のセッション（Session 45）でやること

### 冒頭の確認事項
1. base.htmlの下部メニュー固定が正常に動いているか確認
2. 設定トグルの動作確認

### メイン作業
1. **モニタリング報告書の印刷機能**
   - `history.html`と`monitoring_integration.py`の構造確認から始める
   - 印刷用CSSの実装（`@media print`）
   - 帳票レイアウトのデザイン確認

2. **CSVインポートUIの修正**（バックエンドAPI方式への変更）

---

## 最新コミット状況
- `tasukaru-dev`: `e4a234d`（下部メニュー固定）
- `tasukaru`（本番）: `e4a234d`（同上）

---

**ステータス: 🟢 Session 44-45完了・本番稼働中**
