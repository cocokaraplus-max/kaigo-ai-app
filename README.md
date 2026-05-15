# TASUKARU 介護AI アプリ開発ログ

## 📋 プロジェクト概要
月次評価セクション（要望A）の刷新と実装。音声・ファイル・カメラを用いた元データ集約UI、利用者基本情報DB、AI評価文生成機能の開発。

---

## ✅ Session 44（2026-05-15）完了項目

### 1. assessment.html — 音声入力をMediaRecorder + Geminiに刷新
- **旧実装（Web Speech API）を完全廃止**
- MediaRecorder で録音 → Gemini（`/api/transcribe` / `/api/evaluation/ingest_file`）で文字起こし
- **独り言モード**（職員のみ）/ **対面会話モード**（話者自動分離）のタブ切替
- 待機中 → 録音中 → 一時停止 ⇄ 再開 → 編集・確定 の4状態UI
- 録音中：波形アニメ・リップルエフェクト・タイマー表示
- 停止後：話者別編集エリア・「録り直す」「確定して追加」ボタン
- コミット: `6268ef8`

### 2. input.html — 録音UIをMediaRecorder + Geminiに刷新
- **旧実装（MediaRecorder + 手動「AI文章化」ボタン）を刷新**
- 停止後に自動でGemini文字起こし → 「記録に追加する」で content-area に流し込み
- 独り言モードのみ（対面会話不要）
- 同じく待機・録音中・一時停止・完了編集の4状態UI
- 写真アップロードエリアは**現行デザインのまま完全維持**
- コミット: `a96ec03`

### 3. 技術選定の検討・決定
- AssemblyAI / Whisper WASM / Web Speech API などを比較検討
- **Geminiで統一**（追加費用ゼロ・日本語精度高・話者分離対応・既存スタック流用）
- オフライン対応はネイティブアプリ化時に再検討

---

## ⚠️ Session 44の反省点

### 1. デザイン意図の確認不足
- 「現行デザインを残す」の範囲が何度も食い違った
- **教訓：スクショを受け取ったら「触る箇所」「触らない箇所」を最初に箇条書きで確認する**

### 2. 段階的なデザイン提案が有効
- モックを何パターか見せてから実装に入る流れがうまく機能した
- **教訓：デザインは必ずモックで合意を取ってから実装**

---

## 📋 残タスク（Session 45以降）

### 🔴 優先度高

#### モニタリング報告書の印刷機能
- Session 45で着手予定

#### 第2弾：AI評価文生成
- 元データ（音声・写真・PDF）→ Gemini →「訓練による変化」「課題とその要因」
- `patient_profiles`から利用者情報（介護度・長短期目標・既往歴）をAIに渡す
- `/api/evaluation/generate`エンドポイントを新規作成

#### 利用者基本情報ページの動作確認
- devで`/patient_profile`ページの動作確認
- まもる君CSVの実際の取込テスト（本番環境が必要）

### 🟡 優先度中

#### assessment.htmlとpatient_profilesの連動
- 利用者選択時に`patient_profiles`から介護度・長短期目標を自動セット

#### assessment.html第1弾の復元
- Session 42で作った元データセクションがGitHubに未反映
- 第2弾実装前に復元が必要

### 🟢 優先度低

#### 検索のもたつき改善（記録入力）
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
| `templates/assessment.html` | 月次評価画面（Session 44刷新） |
| `templates/history.html` | モニタリングメニューの実体（注意！） |
| `templates/input.html` | 記録入力（Session 44刷新） |
| `templates/admin.html` | 管理者メニュー（Session 43刷新） |
| `templates/patient_profile.html` | 利用者詳細情報（Session 43新規） |
| `monitoring_integration.py` | モニタリング機能（別ファイル） |

### 音声入力アーキテクチャ（Session 44確定）
| 画面 | 録音方式 | 文字起こし | 話者分離 |
|------|---------|-----------|---------|
| assessment.html | MediaRecorder | Gemini | ✅ 対面会話モード |
| input.html | MediaRecorder | Gemini | ❌ 独り言のみ |
| vitals.html | MediaRecorder | Gemini | ❌ バイタル抽出 |

---

## 📝 次のセッション冒頭でやること

1. モニタリング報告書の印刷機能の実装
   - 現状の`monitoring_integration.py`と`history.html`の構造確認
   - 印刷レイアウト・帳票デザインの検討

---

**最終更新**: Session 44（2026-05-15）
**ブランチ**: tasukaru-dev
**最新コミット**: a96ec03
**ステータス**: 🟢 音声入力UI刷新完了（assessment・input両対応）
