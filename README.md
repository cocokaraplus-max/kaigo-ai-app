# TASUKARU 介護AI アプリ開発ログ

## 📋 プロジェクト概要
月次評価セクション（要望A）の刷新と実装。音声・ファイル・カメラを用いた元データ集約UI、利用者基本情報DB、AI評価文生成機能の開発。

---

## ✅ Session 43（2026-05-15）完了項目

### 1. 利用者基本情報DB構築
- **Supabaseに`patient_profiles`テーブルを新規作成**
  - まもる君クラウドCSV対応項目（利用者番号・氏名・カナ・住所・生年月日・性別・介護度・認定有効期間・支援事業所・担当ケアマネ・委託先事業所）
  - TASUKARU追加項目（既往歴・家族構成・利用開始日・長短期目標・期間）
- **旧`patients`テーブルから51件を`patient_profiles`に移行**（氏名・ふりがな・カルテNo・生年月日）
- **関連テーブルのpatient_idをUUIDに一括更新**
  - `patient_visit_days` ✅
  - `vitals` ✅
  - `vital_daily_excludes` ✅（bigint→text型変換も実施）
  - `vital_recheck_schedules` ✅

### 2. 管理者メニュー刷新
- **admin.htmlを3タブ構成に全面刷新**
  - 利用者管理タブ：CSV取込・写真AIスキャン・手入力登録・一覧編集
  - 職員管理タブ：招待QR・新規登録・権限管理・ブロック
  - 設定タブ：パスワード変更・表示件数・AIカテゴリ振り分け
- **まもる君クラウドCSVインポート機能**（Shift-JIS対応・カタカナ→ひらがな自動変換）
- **patient_profile.html新規作成**（詳細情報・目標設定ページ）

### 3. app.py修正
- `get_patients`関数を`patient_profiles`テーブル参照に統一
- `/patient_profile`ルートとAPIを新規追加
- `/api/add_today_patient`を`patient_profiles`対応に修正
- assessment.htmlのcare_level重複取得を削除

### 4. iPhone利用者検索バグ修正（難航）
- **assessment.html**：UUID対応・候補リストz-index修正
- **history.html**（モニタリングメニューの実体）：touchstart・選択ロックフラグ追加
- **input.html**（記録入力）：addEventListener方式・選択ロックフラグ追加
- `_patientSelected`フラグで選択後の再検索を防止

---

## ⚠️ Session 43の反省点

### 1. ファイルの特定ミス（最大の問題）
- 「モニタリング」ナビメニューが実際には`/history`ページに繋がっていた
- `monitoring.html`を何度修正しても効果がなかった理由
- **教訓：iPhoneのSafari開発者ツールで実際のURLを最初に確認すべきだった**

### 2. Chrome連携の自律操作リスク
- Session 42でClaudeが勝手にGitHubにコミットしてしまった
- コミットメッセージは新しいが中身は旧バージョンという状態が発生
- **教訓：Chrome連携でのGitHub操作は必ず確認を取ること**

### 3. 段階的な確認不足
- iPhoneで「変わらない」が続いた際、Cloud Build反映確認より先にコードを変更し続けた
- **教訓：`curl`でdevのソースを確認してから次の修正に進む**

### 4. patient_idのUUID移行影響範囲の把握が遅れた
- `get_patients`を変更した時点で全テーブルのpatient_idが不一致になることを予測できなかった
- **教訓：テーブル変更時は依存テーブルを先にリストアップする**

---

## 📋 残タスク（Session 44以降）

### 🔴 優先度高

#### 第2弾：AI評価文生成
- 元データ（音声・写真・PDF・テキスト）からGeminiでAI生成
- 出力：「訓練による変化」「課題とその要因」
- `patient_profiles`から利用者基本情報（介護度・長短期目標・既往歴）をAIに渡す
- `/api/evaluation/generate`エンドポイントを新規作成

#### 利用者基本情報ページの動作確認
- devで`/patient_profile`ページの動作確認
- まもる君CSVの実際の取込テスト（列名マッピング確認）
- 管理者メニューの利用者管理タブの動作確認

### 🟡 優先度中

#### assessment.htmlとpatient_profilesの連動
- 利用者選択時に`patient_profiles`から介護度・長短期目標を自動セット
- `/api/patient_profile/get_by_patient_number`APIは実装済み

#### assessment.html第1弾の復元
- Session 42で作った元データセクション（音声・ファイル・カメラ）がGitHubに未反映
- 第2弾実装前に復元が必要

### 🟢 優先度低

#### 検索のもたつき改善（記録入力）
- 一応動くようになったが若干もたつきがある
- blur処理の300msタイムアウトを調整する余地あり

---

## 🏗️ アーキテクチャ現状

### データベース（Supabase: tasukaru-dev）
| テーブル | 用途 | 状態 |
|---------|------|------|
| `patient_profiles` | 利用者基本情報（新） | ✅ 本番運用中 |
| `patients` | 旧利用者テーブル | ⚠️ 残存（削除未実施） |
| `patient_visit_days` | 利用曜日 | ✅ UUID移行済 |
| `vitals` | バイタル | ✅ UUID移行済 |
| `patient_evaluations` | 月次評価 | ✅ 運用中 |

### デプロイ構成
- **GitHub**: `cocokaraplus-max/kaigo-ai-app` / ブランチ: `tasukaru-dev`
- **Cloud Build**: `tasukaru-production`プロジェクト内のトリガー（`tasukaru-dev-auto-deploy`）
- **devサーバー**: `https://tasukaru-dev-191764727533.asia-northeast1.run.app`
- **本番**: `https://tasukaru-191764727533.asia-northeast1.run.app`
- pushから反映まで約2分

### 重要ファイル
| ファイル | 役割 |
|---------|------|
| `app.py` | Flaskメイン（6000行超） |
| `templates/assessment.html` | 月次評価画面 |
| `templates/history.html` | モニタリングメニューの実体（注意！） |
| `templates/input.html` | 記録入力 |
| `templates/admin.html` | 管理者メニュー（Session 43刷新） |
| `templates/patient_profile.html` | 利用者詳細情報（Session 43新規） |
| `monitoring_integration.py` | モニタリング機能（別ファイル） |

---

## 📝 次のセッション冒頭でやること

1. devで動作確認（iPhone）
   - 記録入力の利用者検索
   - 管理者メニュー→利用者管理タブ
   - patient_profileページ（`/patient_profile`）
2. まもる君CSVの実際の取込テスト
3. 第2弾AI評価文生成の実装開始

---

**最終更新**: Session 43（2026-05-15）
**ブランチ**: tasukaru-dev
**最新コミット**: 0ac14c3
**ステータス**: 🟢 利用者DB構築完了・iPhone検索バグ修正完了
