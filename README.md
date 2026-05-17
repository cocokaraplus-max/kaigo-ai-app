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

5. **モニタリング報告書 全面再構築**（monitoring.html + app.py）
   - カテゴリ別モード・まとめて1本モードの2モード実装
   - 文字数選択（100/200/300/400/500字）
   - ハルシネーション対策プロンプト（事実のみ生成）
   - 記録なしカテゴリは「今月このカテゴリの報告はありませんでした」と表示
   - 下書き保存・確定保存・履歴閲覧機能
   - `monitoring_reports`テーブル新規作成（dev・本番両方）
   - 利用者検索を`/api/patients_cache`で実装
   - `/api/save_monitoring`・`/api/monitoring_history`・`/api/monitoring_detail` 新規追加

6. **ナビメニューのデフォルト順修正**（base.html）
   - `/monitoring`を`/assessment`（評価）の前に追加

7. **印刷用報告書レイアウト設計（確定）**
   - 上段左：ケアマネ情報 / 上段右：施設情報＋ロゴ
   - 下段：利用者情報（横並び）
   - モニタリング＋評価を1枚のA4に収めるデザイン確定

8. **LIFE連携 設計決定**
   - 提出用CSV・フィードバックデータ両方対応
   - 加算種別を施設ごとに選択できる設計
   - 科学的介護推進体制加算・個別機能訓練加算のPDCA証跡を自動生成

---

## 🔴 未完了・次回引き継ぎ事項

### 高優先度

1. **~~一括読み上げの二重奏バグ~~** → ✅ Session 48で根本解決済み（_ttsPlaySeqによるシーケンス管理）

2. **~~付箋機能~~** → ✅ Session 48で実装済み

3. **モニタリング報告書 印刷・PDF出力**（次回実装）
   - A4印刷用レイアウト実装（デザイン確定済み）
   - 管理者MENUに施設情報・ロゴアップロード追加
   - admin_settingsに施設名・住所・電話・ロゴURL保存

4. **LIFE連携機能**（次回実装）
   - 管理者MENUで取得加算を選択（個別機能訓練加算・科学的介護推進体制加算等）
   - LIFEからの提出用CSV・フィードバックデータ両方をアップロード対応
   - AIがLIFEデータを読み取りモニタリング報告書に科学的根拠を自動反映
   - PDCAサイクルの記録として保存（加算要件の証跡）

5. **評価ページとモニタリングの統合印刷**
   - 評価＋モニタリングを1枚のA4報告書として出力

6. **新記録追加時のAI要約リアルタイム再生成**
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
- `tasukaru-dev`: `e0d911b`（fix: fix BASE_PROMPT syntax error in monitoring API）
- `tasukaru`（本番）: Session 48前半のみマージ済み（82da954）
- ※モニタリング再構築分は次回dev確認後に本番マージ予定

---

**ステータス: 🟡 Session 48完了・モニタリング再構築dev動作確認待ち・次回印刷/LIFE連携実装予定**

<!-- ===== SESSION 49 HANDOVER (auto-appended) ===== -->

# TASUKARU 介護AIアプリ — Session 49→次セッション 引き継ぎ書

最終更新: 2026-05-18 / 作成: Session 49 終盤（チャット上限のため引き継ぎ）

---

## 0. これは何か

TASUKARU（介護AIアプリ）の開発引き継ぎ書。次に作業するClaudeは、**このチャットの過去ログを読まなくても、本書だけで作業を継続できる**ように書いてある。本書を最初に通読すること。

---

## 1. プロジェクト基本情報（厳守）

- リポジトリ: `cocokaraplus-max/kaigo-ai-app`
- 開発ブランチ: `tasukaru-dev` / 本番ブランチ: `tasukaru`（**main ではない**）
- ローカル: `/Users/ZIMAX 1/dev/kaigo-ai-app/`（スペース含む。ダブルクォート必須）
- dev URL: `https://tasukaru-dev-191764727533.asia-northeast1.run.app`
- 本番URL: `https://tasukaru-191764727533.asia-northeast1.run.app`
- 本番Supabase: プロジェクトID `abvglnkwtdeoaazyqwyd`
- dev Supabase: プロジェクトID `otjevnmoycnvaxeltrtj`
- **重要: dev と prod の DB は完全に別物。** SQL は本番・dev それぞれで毎回実行が必要。コードも各ブランチに毎回 push が必要。「同一参照」という古い記述は誤り（ユーザーが明言済み）。
- push から約2分で Cloud Build が自動デプロイ。
- スタック: Flask（app.py 単一ファイル巨大）、Supabase、Cloud Run、Jinjaテンプレート。

## 2. 作業ルール（厳守）

1. デザイン変更前は必ずモックで合意してから実装。
2. コード変更は `tasukaru-dev` で開発 → dev 確認 → `tasukaru` 本番マージ。
3. 本番マージコマンド:
   ```
   cd "/Users/ZIMAX 1/dev/kaigo-ai-app" && git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru && git checkout tasukaru-dev
   ```
4. DB操作: SELECT は確認不要。INSERT/UPDATE/DELETE/テーブル・カラム作成は **SQLを提示→ユーザー確認→ユーザーがSupabase SQL Editorで本番・dev両方実行**。Claudeは直接DB操作不可。
5. 複雑な文字列置換は Python スクリプトファイル経由。
6. 配置はユーザーがデスクトップにファイルを置き、ターミナルで1行 `python3 ~/Desktop/xxx.py` を実行する方式。配置スクリプトは `.bak.session49xxx-日時` を自動取得してから上書き。
7. コミットメッセージは英語。
8. キャラクター・既存デザインは勝手に変更・削除しない。
9. APIキー・Supabaseキー等の機密情報はチャットに出さない。
10. ユーザーはコード解析が苦手。完成ファイルを提示→デスクトップ配置→1行実行、の確立フローを守る。
11. ユーザーへの選択肢提示は `ask_user_input_v0` ツールを使う（モバイルでタップ回答しやすい）。

## 3. 確立した作業フロー

1. Claude が完成ファイル/スクリプトを作成 → `present_files` で提示。
2. ユーザーがダウンロードしてデスクトップ配置。
3. ターミナルで配置スクリプト1行実行（バックアップ自動取得→上書き）。
4. `git add → commit → push origin tasukaru-dev`。
5. dev 確認 → 問題なければ本番マージ（ルール3のコマンド）。
- 機密マスク用 `scrub.py` が `/mnt/user-data/outputs/scrub.py` にある。
- レイアウト検証に playwright（chromium）が使える。`pip install playwright --break-system-packages` → `python3 -m playwright install chromium`。viewport幅390pxでiPhone相当検証。
- Chrome連携（ブラウザ操作ツール）も使える。ユーザーがdev環境にログイン済みのタブを開いている前提。**ログイン/パスワード入力はClaude代行不可（ユーザーが行う）**。Chrome連携でJS実行・スクリーンショット・DOM実測が可能で、レイアウト検証に有効。

---

## 4. ====== 本番反映済み（完了タスク） ======

**本番ブランチ `tasukaru` 最新コミット: `733a7ce`**（ナビ修正まで反映済み）

### DB（本番・dev両方で実行済み・検証済み）
- `body_weights` テーブル作成済み（体重記録）。
- `fitness_tests` テーブル作成済み（体力測定。grip_right/grip_left/standing_balance_sec/tug_sec/walk_5m_sec/sit_stand_30sec 等）。
- `facilities` テーブルに5カラム追加済み: `facility_postal_code`, `facility_address`, `facility_tel`, `facility_fax`, `facility_logo_url`（全 TEXT DEFAULT ''）。本番・dev両方で確認クエリ照合済み。

### コード（本番反映済み）
1. **体力・体重入力ページ** 新設（`/fitness`、`templates/fitness.html`、API `/api/save_body_weight` `/api/save_fitness_test` `/api/fitness_history`）。base.html ナビに「体力・体重」追加。
2. **評価ページ計測値セクション削除**（assessment.html、体重/出席回数/出席目標の計測値セクションをHTML+JS整合削除）。
3. **全角・半角対応**（app.py に `_to_half_number()`、fitness.html に `fitToHalf()` 等。全角数字→半角変換）。
4. **管理者MENU 施設情報入力欄**（admin.html 設定タブ先頭に section-box 追加、app.py に `/api/admin/facility_info` GET と `/api/admin/save_facility_info` POST 追加。ロゴはBase64で `facility_logo_url` 保存）。プレースホルダーはダミー値（御社実情報は除去済み）。
5. **体力体重ページ iOS Safari レイアウト修正**（体重セクションを横grid→縦並び、日付入力欄に `-webkit-appearance:none` 等。iPhone重なり・はみ出し解消。playwright検証済み）。
6. **ナビ並び替え movableHrefs 不整合修正**（base.html の3箇所 loadNavOrder/startNavEditMode/stopNavEditMode の movableHrefs が食い違っていた既存バグ＋fitness追加漏れを統一。`/monitoring` と `/fitness` を3箇所すべてに含めた）。**今後ナビに項目追加時は movableHrefs 3箇所への追加も必須**（重要知見）。

---

## 5. ====== 進行中（最重要・印刷第2段階：モニタリング報告書） ======

### 5-1. 状況サマリ

「モニタリング報告書の印刷機能」を実装中。**報告書の中身・構成（確定v6）は完成しており正しい。残る課題は『A4印刷時に紙面をしっかり使う表示・印刷の実現』のみ。** ここを詰めている最中にチャット上限。

`tasukaru-dev` の最新コミット: **`e2ea6dd`**（report A4幅最適化・ナビ重なり解消）。**この印刷関連の一連の変更（後述）はまだ本番マージしていない。dev で見た目確定後に本番マージする。**

### 5-2. 確定しているレイアウト仕様（v6 = 実装済み・中身は正しい）

実物Excel報告書（`/mnt/user-data/uploads/IMG_4758.JPG` にあり）をベースに、**TASUKARUの蓄積データを活かしてデジタル進化させた様式**。実物Excelの単純な引き写しではない。確定v6の構成（実装済み・トランスクリプトから復元して中身一致を確認済み）:

- タイトル「モニタリング報告書／評価表」＋作成日（右上）
- ケアマネ枠（左）と施設枠（右）＝**左右2カラム**。施設ロゴは設定時のみ施設名左に表示、未設定なら出さない。施設の〒・住所・TEL・FAXは管理者MENU設定値。ケアマネ情報は `patient_profiles`（support_office / care_manager_name）から自動表示。
- 利用者帯: 氏名の上に小さくグレーでふりがな、その下に大きめ太字で氏名、性別、生年月日（和暦・年齢）、要介護度。右端に**狭い枠で作成担当者**。
- 【短期目標】【長期目標】を**左右2カラム**、各々 機能/活動/参加 の3行＋達成状況（目標継続等）。要介護はICF三軸、要支援/事業対象者は単一（評価ページのデータ構造 care_classification で出し分け）。
- 個別機能訓練実施による変化／課題とその要因 を**左右2カラム**自由記述。
- **モニタリング（カテゴリ別・記録のあるもののみ）**: 心身状況・訓練状況・コミュニケーション等のカテゴリ名＋本文の2列表。**これがTASUKARU中核（AI生成カテゴリ別）。実物Excelの①②③④番号項目とは別物。評価数値1〜5は出さない**（達成度判定ロジック未実装のため根拠ない数字を出さない、という確定方針）。
- **体力測定の推移**: 体重・握力・TUG等のスパークライン、直近6ヶ月、入力のある指標のみ（TASUKARU独自拡張、実物Excelにはない）。
- 特記事項（自由記述）。
- 新しい希望や要望: 「□あり ☑なし」チェックボックス両方表示＋該当にレ点、下に「あり」の場合の内容枠。
- 利用者・家族の満足度・サービス適切性: ○△×でコンパクト表示（○良好/△一部課題/×要改善）＋凡例。
- フッター: TASUKARU自動生成＋日付。
- A4縦・基本1枚。

**注意: 過去に一度「実物Excelの引き写しモック」を誤って作りかけたが、それは誤り。確定はあくまで上記v6（TASUKARUデータ活用版）。** 中身は変えないこと。

### 5-3. 実装済みの内容（dev `e2ea6dd` 時点）

- **app.py**: `/api/monitoring_report_data` を末尾に追加済み（既存無変更）。利用者名・年月を受け、報告書に必要な8データ（patient / caremanager / evaluation / monitoring / fitness / weights / facility / staff_list）を集約して返す。各取得は try/except で空でも安全。
- **monitoring.html**: 確定v6の印刷シート（`#report-sheet` 内 `#rep-root`）、`@media print` CSS、作成者プルダウン（`#rep-author`、staffsから）、サンプルデータでのプレビュー機能を追加済み。既存のモニタリング画面（生成/表示/保存/履歴）は無傷。
  - プレビュー起動: `openReportPreview(true)` でサンプル表示、`openReportPreview(false)` で実データ（選択中利用者・対象月からAPI取得）。結果画面の「報告書プレビュー / 印刷」ボタンが `openReportPreview(false)` を呼ぶ。
  - **`?preview=1` でのURL自動起動は効かない**（このアプリはSPA的でクエリが消える）。検証時は Chrome連携の JS で `openReportPreview(true)` を直接実行する。
  - サンプルデータ関数 `reportSampleData()` に確定モックv6相当の宇井静子サンプルが入っている。

### 5-4. 解決した重要な根本原因（必読）

**アプリ全体が親要素 `page-wrapper`（`max-width:480px`）でスマホ幅に固定されている。** これが「報告書がA4で小さい・縦長・余白だらけ」の真因だった。報告書の幅をいくら指定しても480pxに制限され、各枠が広がらなかった。Chrome連携でDOM実測して特定。

→ 対策として **プレビュー時に `#report-sheet` を `position:fixed` のオーバーレイ化**（z-index 2147483000、全画面、`body.report-preview-open` でナビ非表示）して page-wrapper の外に出した。これにより各枠が横に広がり、A4の縦横比に近づくことを実測で確認済み（幅を広げると縦が圧縮されA4比1.41に近づく。幅約700pxで縦横比≒1.0）。

### 5-5. ★次にやること（中断したそのポイント）★

直前に push した `e2ea6dd` の検証中だった。内容:
- `#report-sheet.preview-on #rep-root` の幅を **740px固定**（max-width:96vw）に（前回 1032px と広がりすぎたのを A4最適幅に絞った）。
- プレビュー中は下部ナビ非表示（`body.report-preview-open .bottom-nav, nav { display:none }`）。
- z-index を 2147483000 に最大化（ナビより前面）。
- `openReportPreview`/`closeReportPreview` で `document.body.classList` に `report-preview-open` を付与/解除。

**次セッションの最初の作業**: dev `e2ea6dd` がデプロイ済みのはず。Chrome連携（ユーザーがdevログイン済みタブを開いている前提。タブ確認は `tabs_context_mcp`）で:
1. `https://tasukaru-dev-191764727533.asia-northeast1.run.app/monitoring?v=新しい値` を開く（キャッシュ回避でクエリ付与）。
2. JS `openReportPreview(true)` を実行。
3. `#rep-root` の幅・高さ・縦横比を実測。狙いは **幅約700〜740px、A4縦（縦横比1.41目安）にバランス良くフィット、1ページに収まる**。
4. スクリーンショットでユーザーに見せ、見た目を確認してもらう。
5. 良ければ **印刷プレビュー（実際の `window.print()` / `@media print`）** も確認。`@media print` 側は `#report-sheet { position:absolute; width:100% }`、`#rep-root { width:100% }`、`@page { size:A4 portrait; margin:8mm }` になっている。印刷時もA4にフィットするか要確認（画面プレビューと印刷で挙動が違うため別途検証必須）。
6. 微調整が必要なら幅・フォント・余白を詰める。**確定v6の中身・構成・HTML構造は絶対に変えない。幅とスケールの調整のみ。**
7. 見た目OK → ユーザーに最終確認 → **本番マージ**（ルール3コマンド）。

**注意点**:
- 画面プレビューと実際の印刷（@media print）は別物。両方確認すること。
- 各報告書要素は固定px指定。`.rep-root` のfont-size変更では全体拡大しない（検証済み）。全体拡大が必要なら `transform: scale()` か幅制御で対応。
- Cloud Build デプロイに2〜3分かかる。ブラウザキャッシュに注意（URLクエリを変えて回避）。
- 印刷検証用のテストデータ（モニタリング/評価/体力体重の実データ）は**まだ無い**（開発中で未実施）。だから**サンプルデータプレビュー（`openReportPreview(true)`）で見た目を確定する方針**。実データ確認は将来テストデータ投入後でよい。

### 5-6. 印刷関連コミット履歴（tasukaru-dev、本番未マージ）

`733a7ce`(本番同期点) → `3760dc0`(報告書データAPI) → `68ebdc6`(印刷レイアウト+プレビュー) → `b83e6c3`(印刷拡大試行・効かず) → `ca4c6f4`(幅フィット試行) → `0485516`(fixedオーバーレイ化＝page-wrapper回避成功) → **`e2ea6dd`(A4幅740px最適化・ナビ重なり解消)** ← 最新・検証中

---

## 6. ====== 残りの保留タスク（印刷完了後） ======

すべて構想・設計は確定済み。印刷第2段階の完了・本番マージ後に着手する。

### A. 目標管理の利用者情報紐付け（独立タスク・規模大）
**設計確定済み（履歴方式）**:
- データの流れ: ①利用者情報ページで介護度（要介護/要支援/**事業対象者**＝事業対象者は選択肢追加が必要）と初回目標を入力。介護区分で構造分岐（要介護＝機能・活動・参加×短期長期の6目標／要支援・事業対象者＝短期長期の2目標）。②評価ページで利用者情報の目標を初期表示、変更時のみ上書き入力。③変更を保存するとその月の評価レコードにその月の目標が記録され（**履歴方式＝各月の目標が残る・正本上書きではない。監査・報告書整合に強い。ユーザーが履歴方式を選択済み**）、次回評価はその最新目標を引き継ぐ。
- 現状: 評価ページに既に介護区分による目標構造の出し分け実装あり（要介護=`eval-status-kaigo` ICF三軸6欄、要支援等=`eval-status-simple` 2欄）。`training_goal` は前月評価から引き継ぐ（`get_initial_training_goal`）。**現状、目標欄は利用者情報 patient_profiles の long_goal/short_goal と紐付いていない**。
- **前提: `evaluation_helper.py`（目標引き継ぎ・upsert・バッジ判定の中核）が未取得。実装にはこのファイルの取得・確認が必須。** scrub.py 経由でマスク版取得を依頼すること。
- 最も重い作業: 利用者情報ページの目標欄を介護区分別構造に拡張（patient_profiles カラム設計）。

### B. バイタル入力改修4項目（vitals.html 約3559行、/api/save_vital 周辺）
1. 全角数字自動半角化（`_to_half_number`/`fitToHalf` の移植、低リスク）。
2. 音声入力のメモ分離（数値の音声入力とメモ音声入力を別に。`/api/vital_voice_parse` 要確認）。
3. 保存後の数値クリア（1回目保存後に数値を自動クリア）。
4. 体温入力の分離（血圧の後すぐ体温を測れない運用に対応。保存ロジック・再検査アラート・vitalsテーブル構造に影響しうるため要調査）。

### C. PC専用一括入力画面（新機能・データ移行効率化）
PCでブラウザ幅いっぱい表示、利用者情報・体力体重・バイタル等をExcelライクに一括入力。論点多数（PC判定方法、UI形式、既存スマホ画面との関係、CSVインポートとの使い分け）。独立タスク・構想段階。

### D. 方式B（サーバーPDF生成・完全固定）
将来タスク。現在の印刷は方式A（ブラウザ印刷=window.print()+@media print、A4印刷とPDF保存兼用）で実装中。方式Bは WeasyPrint＋Dockerfileにシステムライブラリ(libcairo2等)・日本語フォント(IPAex/Noto Sans JP)埋込・requirements変更・ビルド検証が必要。デプロイ構成変更を伴う独立タスク。ユーザーは「まず方式Aで実用化→方式Bは後で独立タスク」と決定済み。

---

## 7. ====== コード調査結果（実装に有用・調査済み） ======

- **既存ヘルパー(app.py)**: `get_supabase()`, `login_required`, `render()`(partial対応), `get_patients()`(戻り値: value,label,id,chart_number,patient_number,user_name,user_kana,user_name_kana,birth_date,birth_text,care_level,long_goal,short_goal), `birth_to_wareki_text()`, `/api/patients_cache`。session: `f_code`, `my_name`。
- **app.pyは末尾追加方式厳守**（既存関数を一切変更せず新規ルートを末尾に追加。行ずれゼロ）。現在ルート数 約170。
- **モニタリング**: `monitoring_reports` テーブル。API `/api/generate_monitoring` `/api/save_monitoring` `/api/monitoring_history` `/api/monitoring_detail`。カテゴリ8固定: 心身状況・食事・入浴・排泄・コミュニケーション・訓練状況・ヒヤリハット・その他。記録なしは「今月このカテゴリの報告はありませんでした」。
- **評価**: `patient_evaluations` テーブル。`/api/get_patient_evaluations` `/api/get_patient_evaluation`(年月指定で1件)。`evaluation_helper.py`（未取得）。実装フィールド: user_name, year_month, evaluator_name, care_classification, training_goal, changes_by_training, issues_and_causes, special_notes, new_requests_exist, new_requests_detail, satisfaction, service_appropriateness, short_goal_*_status, long_goal_*_status 等。介護区分: 要介護=ICF三軸6欄、要支援/事業対象者=短期長期2欄。
- **ケアマネ情報**: `patient_profiles` テーブル: `support_office`, `care_manager_name`, `delegate_office`, `care_level`。介護度欄に**事業対象者の選択肢が抜けている**（タスクAで追加要）。
- **バイタル**: `vitals` テーブル（patient_id, measured_date, bp_high, bp_low, pulse, temperature, spo2, note, recheck, staff_name）。`/vitals` `/api/save_vital`(upsert) `/api/vital_voice_parse`。
- **施設情報**: `facilities` テーブル（facility_code, facility_name, admin_password, plan_limit, is_active, expires_at ＋追加5カラム）。画像はBase64方式（Supabase Storageは未使用）。
- **職員リスト**: `staffs` テーブル。`supabase.table("staffs").select("staff_name").eq("facility_code",f_code).eq("is_active",True)` で取得。
- **base.htmlナビ構造**: `{% block bottom_nav %}`、各項目 `<a href="/xxx" class="bottom-nav-item {% block nav_xxx %}{% endblock %}" onclick="spaNav(event,'/xxx')">`。デザイン: 青#1a73e8、角丸カード、Material Symbols。**ナビ追加時は movableHrefs 3箇所（loadNavOrder/startNavEditMode/stopNavEditMode）への追加必須**。
- **page-wrapper**: アプリ全体を `max-width:480px` に制限する親要素。全画面表示が必要な時は position:fixed 等で外に出す必要あり（報告書プレビューで対処済み）。
- **admin.html構造**: 3タブ（tab-patients/tab-staff/tab-settings）。施設情報欄は tab-settings 先頭に追加済み。

## 8. アップロード済み参考ファイル

`/mnt/user-data/uploads/` に旧版マスクファイル: app.py(旧6618行), templates__monitoring.html(502行・素のbase.html継承版), templates__assessment.html, templates__base.html, templates__admin.html, templates__vitals.html, templates__input.html, templates__patient_profile.html。**いずれも旧版。最新は本番/dev反映済みの別状態なので注意**。実物Excel報告書写真 `IMG_4758.JPG` あり（報告書レイアウトの原典）。

トランスクリプト: `/mnt/transcripts/` に過去会話ログ2本＋ `journal.txt`（カタログ）。確定v6モックの完全HTMLは `2026-05-17-20-49-01-...txt` の 6687行付近（`monitoring_print_layout_v5` widget）に記録あり。

## 9. 次セッション開始時の最初のアクション

1. 本書を通読。
2. ユーザーに「印刷第2段階の続きから再開します。dev `e2ea6dd` の報告書プレビューをChrome連携で確認します」と伝える。
3. `tabs_context_mcp` でdevログイン済みタブを確認（無ければユーザーにdevを開いてもらう）。
4. §5-5「次にやること」の手順を実行。
5. 見た目確定 → ユーザー確認 → 本番マージ → 残タスク（§6 A〜D）の優先順位をユーザーに確認して進める。

