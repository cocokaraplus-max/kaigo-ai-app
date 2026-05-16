# TASUKARU 介護AIアプリ 開発引き継ぎドキュメント
**最終更新: Session 48（2026-05-17）**

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
| dev Supabase | project ID `otjevnmoycnvaxeltrtj`（※devとprodは同じSupabaseを参照中） |
| ローカルリポジトリ | `/Users/ZIMAX 1/dev/kaigo-ai-app/` |
| デプロイ | pushから約2分でCloud Build自動デプロイ |
| Cloud Buildプロジェクト | `TASUKARU-production` |

---

## ⚠️ 重要：ブランチとデプロイの仕組み

| ブランチ | Cloud Runサービス | URL | 設定ファイル |
|---|---|---|---|
| `tasukaru-dev` | `tasukaru-dev` | `https://tasukaru-dev-191764727533...` | `cloudbuild-dev.yaml` |
| `tasukaru` | `tasukaru` | `https://tasukaru-191764727533...` | 別トリガー |

**→ `tasukaru-dev`にpushするとdev環境に自動デプロイ。本番は`tasukaru`ブランチへのマージが必要。**

---

## 📋 作業ルール

1. デザイン変更前 → モックアップ確認
2. コード変更 → `tasukaru-dev`で開発 → `tasukaru`本番にマージ
3. 本番マージコマンド:
   ```bash
   cd "/Users/ZIMAX 1/dev/kaigo-ai-app"
   git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru && git checkout tasukaru-dev
   ```
4. DB操作: SELECT→確認不要、INSERT/UPDATE/DELETE→内容提示→確認→実行
5. 複雑な文字列置換はPythonスクリプトファイル経由（ターミナルでの直接入力は文字化けするため）
6. コミットメッセージは英語
7. スクリプトはダウンロードして`~/Desktop/`に置いて実行（`~/dev/kaigo-ai-app/`ではなく）

---

## ✅ Session 46-47 完了項目

### Session 46（前回）
1. **ケース記録 AI要約機能**（daily_view.html）
2. **個別記録のモーダル表示**
3. **Google Cloud WaveNet TTS実装**（サーバー経由MP3生成→再生）
4. **TTS施設別制御**（admin_settings DBで管理）
5. **ルート・命名整理**（/history → /case_records）
6. **バグ修正**（base.html JS SyntaxError、patient_profile セッションキーバグ、カルテ番号復元）

### Session 47（今回）完了
1. **TTSテスト再生エラー修正**
   - 原因：APIキーの制限が`Cloud Speech-to-Text API`（音声認識）になっていた
   - 正しくは`Cloud Text-to-Speech API`（音声合成）に変更して解決
   - エラー内容: `403 Forbidden` → APIキー設定ミス

2. **WaveNet → Neural2 音声グレードアップ**
   - 料金変わらず（同じ無料枠内）でより自然な声に
   - DB: `tts_voice` = `ja-JP-Neural2-B`（女性・標準）に変更
   - `app.py`: genderの判定リストにNeural2の音声名を追加
   - admin.htmlの選択肢をNeural2に更新

3. **ケース記録の読み上げをNeural2（/api/tts_speak）に変更**
   - 従来：Web Speech API（ブラウザ内蔵のロボット声）
   - 変更後：Google Neural2 TTS経由
   - daily_view.htmlのTTSブロックを全面書き換え

4. **一括読み上げ機能の大幅改修**（daily_view.html）
   - 「全員分読み上げ」ボタンに前の方/停止/次の方コントロール追加
   - 進捗表示「〇〇様（N/M）」
   - アコーディオンを自動展開してAI要約を生成してから読み上げ開始
   - iOS対応：AudioContext経由で再生（iOSの自動再生制限を回避）
   - 画面オフ防止（Wake Lock API）
   - 停止ボタンでcheckIntervalもキャンセル
   - onendedをクリアしてから停止（二重再生防止）

5. **TTS表示バグ修正**
   - `speak-all-bar`が常に非表示になっていたバグ修正
   - TTS有効時にボタンを表示するロジックを追加

6. **APIキーのローテーション**
   - 漏洩したAPIキーを削除し新しいキーに差し替え
   - 本番・dev両方のCloud Run環境変数を更新

7. **dev環境のGOOGLE_TTS_API_KEY設定**
   - dev Cloud Runサービスに環境変数を追加

---

### Session 48（今回）完了
1. **TTS二重奏バグ根本修正**
   - `_ttsPlaySeq`シーケンス番号を導入
   - `fetch`→`decodeAudioData`→`onended`の非同期チェーンが古くなったら自動無視
   - `_ttsStop()`でシーケンスをインクリメントして飛行中の処理を全キャンセル
   - レースコンディションによる二重再生が解消

2. **付箋機能追加**（daily_view.html）
   - 各利用者行の右端に🔖ボタン追加
   - `localStorage`（キー: `tasukaru_bookmark_v2`）で当日分のみ保存
   - 「続きから読む」バーでスクロールジャンプ
   - 日付をまたぐと自動リセット、1つのみ・この端末限定

3. **アコーディオンヘッダーUI改善**（daily_view.html）
   - chevron（∨）を青色・22pxに変更して視認性向上
   - 付箋ボタンを右端固定、タップ領域拡大（padding拡張）
   - `.user-accordion-title`に`flex:1`追加してレイアウト安定化

4. **ガイドページ更新**（manual.html）
   - 「AI読み上げ」セクション追加（タスカルくんふきだし・UIモックアップ・ステップ解説）
   - 「付箋機能」セクション追加（同上）
   - 目次にも両セクションのリンク追加（`#s-tts`, `#s-bookmark`）

---

## 🔴 未完了・次回引き継ぎ事項

### 高優先度

1. **~~一括読み上げの二重奏バグ~~** → ✅ Session 48で根本解決済み（_ttsPlaySeqによるシーケンス管理）

2. **~~付箋機能~~** → ✅ Session 48で実装済み

3. **モニタリング報告書の作り込み**（Session 48で着手予定）
   - 月次AI書類作成の本格実装
   - 印刷機能

4. **新記録追加時のAI要約リアルタイム再生成**
   - 現状はページリロードで反映（リアルタイム検知は未実装）

### 中優先度
4. **モニタリング報告書の印刷機能**
5. **CSVインポートUIのバックエンドAPI化**（/api/import_csv新規作成）

### 低優先度
6. **カナの半角濁点修正**（patient_profiles.user_name_kana）
7. **patient_visit_daysの今井広子・板倉篠麿の整理**（数値IDのレコード3件あり）

---

## 🗄️ DB現状（本番: abvglnkwtdeoaazyqwyd）

| テーブル | 状態 |
|---|---|
| `patient_profiles` | ✅ 81件（カルテ番号復元済み） |
| `daily_summaries` | ✅ 新規作成済み（AI要約キャッシュ） |
| `admin_settings` | tts_enabled/tts_voice/tts_speed/tts_pitch（cocokaraplus-5526）設定済み |
| `patient_visit_days` | ⚠️ 数値IDのレコード3件残存 |

### admin_settings（cocokaraplus-5526）現在値
| key | value |
|---|---|
| tts_enabled | true |
| tts_voice | ja-JP-Neural2-B |
| tts_speed | 1.2 |
| tts_pitch | 0 |

---

## 🗂️ 重要ファイルマップ

| ファイル | 役割 |
|---|---|
| `app.py` | Flaskメイン（6000行超） |
| `templates/base.html` | 共通レイアウト・下部ナビ |
| `templates/daily_view.html` | ケース記録閲覧（AI要約・読み上げ・モーダル機能含む）3500行超 |
| `templates/monitoring.html` | モニタリング（月次AI書類作成） |
| `templates/admin.html` | 管理者メニュー（TTS音声設定含む） |
| `templates/dev_menu.html` | 開発者メニュー（TTS ON/OFF含む） |
| `templates/patient_profile.html` | 利用者詳細情報 |

---

## 🔑 APIエンドポイント一覧（TTS関連）

| エンドポイント | 説明 |
|---|---|
| `GET /api/daily_records` | 指定日の全利用者ケース記録を返す |
| `POST /api/generate_daily_summary` | 利用者×日付のAI要約生成＆キャッシュ |
| `GET /api/tts_enabled` | 施設のTTS有効フラグを返す |
| `POST /api/tts_toggle` | 開発者のみTTS ON/OFF切り替え |
| `GET /api/tts_settings` | 施設のTTS設定を返す |
| `POST /api/tts_settings` | TTS設定を更新 |
| `POST /api/tts_speak` | Google Neural2 TTSで音声合成してMP3（base64）を返す |

---

## 💡 TTS実装メモ

### 音声の種類（Neural2・日本語）
| 名前 | 性別 | 特徴 |
|---|---|---|
| ja-JP-Neural2-A | 女性 | 落ち着いた声 |
| ja-JP-Neural2-B | 女性 | 標準（現在設定中） |
| ja-JP-Neural2-C | 男性 | 低めの声 |
| ja-JP-Neural2-D | 男性 | はっきりした声 |

### 料金
- 無料枠: 100万文字/月（Neural2・WaveNet共通）
- 現在の利用規模（月32万文字程度）は**無料枠内**

### Google Cloud APIキー
- キー名: `API key (TEXT to speech)`
- 制限: `Cloud Text-to-Speech API`のみ
- 環境変数名: `GOOGLE_TTS_API_KEY`
- 本番・dev両方のCloud Runに設定済み

### iOS対応（重要）
- iOSはユーザー操作なしの`audio.play()`をブロックする
- 対策：`AudioContext`を使って無音再生でアンロック（`_ttsUnlockAudio()`）
- AudioBufferSourceNodeは`pause()`が使えない → `stop()`を使う
- `stop()`前に`onended = null`しないと二重再生が起きる

---

## 💻 開発環境

| 項目 | 内容 |
|---|---|
| Mac | `/Users/ZIMAX 1/dev/kaigo-ai-app/` |
| ブラウザ | Chrome（Claude in Chrome拡張機能インストール済み） |
| Python | `/Library/Frameworks/Python.framework/Versions/3.14/` |
| スクリプト置き場 | `~/Desktop/`（文字化け防止のため`~/dev/`ではなくデスクトップ） |

---

## 最新コミット状況
- `tasukaru-dev`: `40c9029`（feat: add AI TTS and bookmark sections to user guide）
- `tasukaru`（本番）: Session 48の変更がマージ済み（82da954）

---

**ステータス: 🟢 Session 48完了・TTS二重奏バグ解決・付箋機能追加・ガイド更新済み**
