# TASUKARU 開発 README

介護AIアプリ「TASUKARU」の開発ドキュメント。次セッションの冒頭でこのファイルを読めば、現状・完了済み・残タスクが把握できる。

---

## 1. プロジェクト基本情報

| 項目 | 内容 |
|---|---|
| ローカルパス | `/Users/ZIMAX 1/dev/kaigo-ai-app` |
| 構成 | Flask + Supabase + Cloud Run |
| DEVブランチ | `tasukaru-dev` |
| 本番ブランチ | `tasukaru` |
| DEV URL | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| 本番URL | https://tasukaru-191764727533.asia-northeast1.run.app |
| GitHub | cocokaraplus-max/kaigo-ai-app |
| GCPプロジェクト | tasukaru-production（リージョン asia-northeast1） |
| 運営会社 | 合同会社LIFE PLUS |

### 主要ファイル
- `templates/print_preview.html` … モニタリング報告書プレビュー（約3,400行）
- `templates/print_output.html` … 書類出力設定画面
- `templates/vitals.html` … バイタル測定ページ（測定・本日の記録・履歴・設定タブ。約4,000行超）
- `app.py` … バックエンド本体
- `evaluation_helper.py` … 評価データのUPSERTヘルパー
- `templates/dev_menu.html` … 開発者MENU

### 検証用利用者
- 青木 利夫（レーダー表示 = `chart_style=6`）

---

## 2. 開発の進め方（厳守ルール）

1. **Claudeはローカルを直接操作できない。** ユーザーがVSCodeターミナルでコマンドを実行し、結果を貼り付ける。コマンドは半角英数のみ。
2. **パッチ方式（冪等Python）またはファイル全体差し替え**（`cp ~/Downloads/file templates/`）。サンドボックスでJS構文（`node --check`）・CSS波括弧・Jinja `{% if %}`/`{% endif %}` の整合を検証してから渡す。
3. **Chrome連携での実測はDEV環境のみ。** 本番URLは操作しない。憶測修正を避け、実測してから実装する。
4. **本番反映手順:**
   ```
   git checkout tasukaru
   git merge tasukaru-dev
   git push origin tasukaru
   git checkout tasukaru-dev
   ```
5. **セキュリティ:** Stripe Secret Key（`sk_...`）、LINE Channel Access Token/Secret 等のシークレットは画面・ドキュメントに一切出さない。Price ID（`price_...`）は公開識別子なので記載可。

### JavaScript TDZ問題（重要）
`let`/`const` で宣言した変数が、それを参照する関数より後にあるとエラーになる。グローバル変数は `window.xxx` 形式を使う。
```javascript
// NG
let allAccounts = [];
// OK
window.allAccounts = [];
```

---

## 3. 完了済み機能（print_preview / print_output 系）

すべて本番反映済み。

- **あふれ判定の誤検知修正**（page-number除外）
- **レーダー横並びレイアウト仕上げ**
  - 上下端揃え・幅比 55:45（graph-col は `flex:1 1 0` + `min-width:0`、special-col は `flex:0 0 45%` + `min-width:0`）
  - 「体力測定の推移」を外枠左端上 / 「直近6ヶ月」を外枠右端上
  - 参考文献を外枠フル幅で折り返し、グラフ枠（rep-radar-wrap）を外枠フル幅
  - グラフサイズ（ss/s/m/l）変更でも下端揃いが維持されることを実測確認済み
- **変化・課題・特記事項のプレビュー編集保存**
  - 3項目を `contenteditable` + `data-user`/`data-field` 化
  - `repSaveEvalText()` で `/api/save_patient_evaluation` へ `{user_name, year_month, changes_by_training, issues_and_causes, special_notes}` をPOST
  - 3項目とも `ALLOWED_UPSERT_KEYS` に既存のためサーバ変更不要
- **ページ番号（1/1）を印刷時のみ非表示**
  - `@media print` に `.page-number { display: none !important; }`。画面では表示（あふれ判定の基準に使うため）
- **フォント倍率（ページ全体一括・利用者ごと保存）**
  - 全体一括・1%刻み・50〜150%・利用者ごとサーバ保存
  - DB: `patient_evaluations` に `font_scale numeric DEFAULT 1.0` 追加済み（dev/prod両方）
  - `evaluation_helper.py` の `ALLOWED_UPSERT_KEYS` に `"font_scale"` 追加済み
  - **方式:** zoom方式は不採用（論理px問題であふれ判定が破綻）。`transform: scale()` + width補正（`width:100/s %`）+ rectベース判定を採用。中身を `.rep-scale-wrap`（`transform-origin:top left`）で自動ラッパー化（page-number/overflow-badgeは包まず外に残す）
  - JS関数群: `repApplyFont`/`repFontStep`/`repFontReset`/`repSaveFontScale`（600msデバウンス）/`repRectOverflow`/`repUpdateOverflowBadge`
  - Chrome実測で scale 0.7/1.0/1.3/1.5 すべて rect判定が追従、150%でも収まることを確認済み
- **配置切り替え（special_layout）機能の撤去**【このセッションで完了・本番反映済み / commit `c434c2e`】
  - print_output.html: 特記事項配置選択UI・`poSpecialLayout` 変数・UI初期化forEach・`poSetSpecialLayout` 関数・パラメータ送信2箇所を削除
  - print_preview.html: CSS `[data-layout="side"]`/`[data-layout="inline"]` ルール削除（`[data-layout="below"]` は `flex-direction: column` で土台として残置）、`special_layout_param` 即時関数・未使用の `setSpecialContainerLayout`/`initSpecialContainerLayout` を削除
  - 写真レイアウトの `setLayout`/`data-layout="A/B/C"`（rep-layout-btn）は別機能のため温存
  - DEV実測済み: 横並びレイアウト無傷、特記事項は縦並び（下配置）、下端差0px、残骸ゼロ

### 既知事項
- `chart_size` 内部値: s=1, m=2, l=3, ss=4
- レーダーは厚労省「介護予防マニュアル改訂版 資料3-5」基準（全年齢・男女別）、出典文は維持必須
- 行特定キー: `(facility_code, user_name, year_month)`。`/api/save_patient_evaluation` はUPSERT・編集ロック（conflict/editing_by）完備

---

## 4. 次にやるタスク（print系）

### 【任意・保留】フォント機能と既存あふれ判定の完全統合
- 現状はフォント時専用のrect判定 + 既存 `detectOverflowPages` にラッパー透過分岐で実用上OK（A案）
- 完璧な一本化（既存判定もrectベースに統一 = B案）は将来検討。分割機能への波及確認が必要なため保留中

---

## 5. 決済（Stripe）・LINE連携 — 残タスク

> 別系統の大型タスク。2026/05/22〜05/24 のセッション（Session 59〜「招待機能とサブスク決済」）で土台を実装。print系のHANDOFFには引き継がれていなかったため、ここに統合して記録する。**未完了が多く、本番課金前に要総点検。**

### 5-1. これまでに完了済み（5/22〜5/24）
- Stripe / LINE Messaging API のアカウント・チャンネル作成（**サンドボックス／テスト環境**）
- 料金プラン確定（3プラン × 7パターン = 全21価格）、Price ID 取得
- Cloud Run 環境変数 設定済み（LINE/Stripeキー、21個のPrice ID）
- `app.py` にAPI実装:
  - `POST /api/line/webhook` … LINEからのWebhook受信
  - `POST /api/line/send_invite` … 施設管理者・スタッフへの招待メッセージ送信
  - `line_notify_admin(message)` … 管理者（岸本さん）のLINEに通知
  - `POST /api/stripe/create_checkout` … 決済セッション作成→URLを返す
  - `POST /api/stripe/webhook` … 決済完了時の自動有効化・解約処理
- 事業計画書 v3・顧客向け料金案内 docx 作成
- Stripe商品画像（タスカルくん）生成済み: `make_stripe_v2.py`

### 5-2. 料金プラン（確定版）

| プラン | 月払い | 1年月払い | 1年一括 | 2年月払い | 2年一括 | 3年月払い | 3年一括 |
|---|---|---|---|---|---|---|---|
| スターター | ¥5,980 | ¥4,780 | ¥57,400 | ¥3,880 | ¥93,300 | ¥2,990 | ¥107,600 |
| スタンダード | ¥12,800 | ¥10,240 | ¥122,800 | ¥8,320 | ¥199,700 | ¥6,400 | ¥230,400 |
| プロ | ¥24,800 | ¥19,840 | ¥238,100 | ¥16,120 | ¥387,100 | ¥12,400 | ¥446,400 |

- 割引率: 1年 20%OFF（解約時 残期間の30%違約金）／ 2年 35%OFF（同40%）／ 3年 50%OFF（同50%）
- 課金形態: **`_M`系（単月・1Y_M・2Y_M・3Y_M）= 毎月課金（subscription）／ `_L`系（1Y_L・2Y_L・3Y_L）= 一括1回払い（payment）**
- Price IDキー命名: `STRIPE_PRICE_{PLAN}_M` / `STRIPE_PRICE_{PLAN}_{1Y|2Y|3Y}_{M|L}`（PLAN = STARTER/STANDARD/PRO）
- 無料トライアル: 全プラン1ヶ月

### 5-3. プラン別機能

| 機能 | スターター | スタンダード | プロ |
|---|---|---|---|
| スタッフ数 | 〜5名 | 〜15名 | 無制限 |
| AI記録/月 | 100件 | 500件 | 無制限 |
| 出納帳（基本） | ○ | ○ | ○ |
| CSV取込・OCR | × | ○ | ○ |
| LINE通知 | × | ○ | ○ |
| 事業間資金移動 | × | × | ○ |
| 追加スタッフ | ¥500/名 | ¥500/名 | 不要 |

- **モニタープログラム:** 開発者MENUから個別に施設を選定・許可。スターター相当を無料提供（条件: 月1回以上のフィードバック）

### 5-4. 残タスク（優先度順）

#### 優先度・高
1. **Supabase に契約管理カラム追加（dev・prod両方、未実施の可能性が高い → 要確認）**
   ```sql
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free';
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS contract_term INTEGER DEFAULT 0;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS payment_type TEXT DEFAULT 'monthly';
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS contract_start DATE;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS contract_end DATE;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS cancellation_fee_rate FLOAT DEFAULT 0;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS is_monitor BOOLEAN DEFAULT FALSE;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS approved_by_admin BOOLEAN DEFAULT FALSE;
   ALTER TABLE facilities ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
   ```
2. **Stripe Webhook URL の登録 + Webhook Secret 設定**
   - StripeダッシュボードでエンドポイントURL `.../api/stripe/webhook` を登録
   - 取得した Secret を Cloud Run の `STRIPE_WEBHOOK_SECRET` に設定
3. **`create_checkout` のキー生成バグ修正**
   - 旧版コードが `STRIPE_PRICE_BASIC/PRO` や `STRIPE_PRICE_{PLAN}_1Y`（末尾の `_M`/`_L` 欠落）を参照している箇所がある
   - 入力を3軸で受ける: `plan`(starter/standard/pro) / `term`(M/1Y/2Y/3Y) / `pay`(M=毎月課金/L=一括)
   - `_L` 系は `mode="payment"`、`_M`・単月は `mode="subscription"`
   - Webhook側: `metadata` に term/pay を持たせ、`expires_at` を契約年数で正しく計算（30日固定をやめる）。plan デフォルト `"basic"` → `"starter"` に修正
4. **決済フロー画面の実装（app.py + HTML）**
   - プラン選択 / 契約期間（月・1/2/3年）/ 支払方法（月払い・一括）→ Stripe Checkout へリダイレクト
5. **LINE 承認処理の実装**
   - `line_webhook` 内の「将来的な承認処理」が未実装（コメントのみ）
   - 管理者がLINEで「承認」返信 → 該当施設の有効化フラグ書き込み → ユーザーへ通知
6. **開発者MENUに契約管理・モニター設定画面**
   - 施設一覧（契約状況・残日数・プラン）/ プラン変更・モニター設定ON/OFF・有効期限設定 / 違約金自動計算 / 解約処理

#### 優先度・中
7. **契約期限通知システム**（Cloud Schedulerで毎日実行）
   - 施設へ: 90日前・30日前・7日前にLINE/メール通知
   - 管理者（岸本さん）へ: 60日前にLINE通知（更新交渉タイミング）
   - 支払い失敗時: 即時LINE通知
8. 掲示板「さらに読み込む」ボタン
9. `utils.pycode` ファイルの削除（`git rm utils.pycode`）

#### 優先度・低
10. 本番Stripeアカウントへの切替（本番リリース前）
11. LINE認証済みアカウントへの申請

### 5-5. LINE Messaging API 設定情報
- プロバイダー名: TASUKARU / チャンネル名: TASUKARU（LINE公式アカウント連携済み）/ ステータス: 利用中
- 環境変数（値はCloud Runに設定済み・ローカル管理。**ここには値を書かない**）:
  `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_CHANNEL_SECRET` / `LINE_ADMIN_USER_ID` / `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`（要設定）/ 21個の `STRIPE_PRICE_*`

---

## 6. 作業手順テンプレート
1. コード確認 … `grep -n` / `sed -n` で現状把握
2. パッチ生成 … 冪等Pythonスクリプトを作成 → Outputsにダウンロード → ユーザーが実行
3. サンドボックス検証 … `node --check`・CSS波括弧・Jinja整合
4. DEV反映 … commit → push → ビルド完了確認
5. DEV実測 … Chrome連携でDEVのみ確認
6. 本番マージ … §2の手順

## 7. バイタル機能（2026-06-04 セッション・本番反映済み）

体温音声入力の精度・誤登録防止と、測定UIの刷新。本番反映は2回に分割。
- 1回目 commit `17b422a`: 読み仮名照合+確信度UI / 10分グルーピング / 測定UI第1段 / メモ機能
- 2回目（無音バグ対応一式）: `7e718f5`〜`5c17d68` を本番マージ（誤登録防止の重要修正）
対象: `templates/vitals.html`（フロント）/ `app.py`（バックエンド `api_vital_bulk_temp`）。

### 7-1. 体温一括入力の読み仮名照合 + 確信度UI
- 当て字対応の核心。例「倍子（ますこ）」を音声「ますこさん」で本人に当てる。
- フロントが名簿に `user_kana` を載せて送信。サーバ `/api/vital_bulk_temp` が「漢字（よみ）」名簿をGeminiに渡し、さらに読み仮名ベースの fuzzy 照合（`_voice_norm`/`_voice_match_temp`）で再検証し `confidence`（high/mid/none）を付与。
- 緑(high=自動登録)／黄(mid=職員が氏名を確定するまで登録しない)／赤(none=対象外)。`confirmYellowTemp` で黄を確定。

### 7-2. 10分枠グルーピング + 複数測定の印 + 履歴モーダル
- 「本日の記録」で測定を10分スライド枠でまとめる（直近測定から10分以内＝同枠）。日付境界で切らず「10分の途切れ」が日の区切り（お泊まり対応）。
- 同枠に同項目複数→最新値を代表表示＋印(●)、クリックで `openVitalHistoryModal`。表示層のみ（`groupVitalWindows`）、生データは `_rawItems` に退避・非破壊。

### 7-3. 測定タブ 新UI 第1段（案B 骨組み）
- 測定タブを「一覧（2列コンパクトカード）」⇔「測定画面（個人フォーム）」の2状態に（`window._measureView`、`openMeasure`/`backToMeasureList`）。カードタップで測定画面へ、保存後は自動で一覧へ。

### 7-4. メモ機能
- メモ入力欄をフル幅化＋音声ボタンを右隣に（重なり解消）。「本日の記録」のメモ有り行に青アイコン（edit_note）＋タップで `openVitalNoteModal`（`_vitalNoteCache` 経由）。
- **DBカラム追加: `vitals` に `note TEXT DEFAULT ''` を dev/prod 両方に追加済み**（無いと保存されない）。

### 7-5. 体温一括の無音バグ対応（誤登録の根絶）
- 症状: 無音で停止しても、Geminiが会話・体温を捏造し、緑で複数名が登録予定に並んだ。
- 対策(多層):
  - サーバ(app.py): プロンプトに「無音・聞き取れない場合は推測せず空で返せ」明示／結果が空transcript＋0件なら「音声を検出できませんでした」／音声2KB未満を弾く。
  - フロント(vitals.html): **録音中に Web Audio API で音量(RMS)監視**し、有効発話が検出されなければGeminiに送信しない（捏造を入口で遮断）。`startBulkVoiceMonitor`/`stopBulkVoiceMonitor`、`window._bulkVoiceDetected`。
  - しきい値 `BULK_VOICE_RMS_THRESHOLD = 0.05`（実測: 無音 最大RMS≈0.0218 / 発話 0.0955〜0.2083 の中間）。`BULK_VOICE_MIN_HITS = 8`。**現場の声を聞いて調整予定**（この1行の数値を変えるだけ。無音が通るなら上げ、小声が弾かれるなら下げる）。

### 7-6. 累積保持 + クリアボタン + 回数セレクタ撤去
- 解析のたびにクリアせず、緑(確定)を登録予定リストに累積（同一pidは上書き）。黄は職員が確定したら昇格、赤(未検出)は抹消。描画は `renderBulkTempResults()` に分離。
- 「クリア」ボタン追加。登録後は自動クリア。
- 回数セレクタ（旧 `bulk-temp-order`）は撤去（回次は10分グルーピングが時刻から自動決定するため不要）。

### 7-7. 次にやる残タスク（バイタル）
- **測定UI 第2段**: 検索窓（名前・ふりがな・カルテ番号の部分一致、既存 `_patient_matches_query`/`filterAddPatientList` 流用）＋ 全員/午前/午後タブを測定タブ上部に。
- **測定UI 第3段**: 進捗バー（○/○名）＋ 済/未の色分け ＋ カード下段の表示切替（バイタル要約⇔ふりがな+カルテ番号）。
- **ガイド更新**: `templates/manual.html` のバイタル記述を新機能に合わせ更新。
- 任意: 無音しきい値の現場調整、10分枠の上限時間、印デザイン。

---

_最終更新: 2026-06-04（バイタル機能群を実装・本番反映。読み仮名照合+確信度UI/10分グルーピング/測定UI第1段/メモ機能=commit 17b422a、無音バグ対応一式(音量監視・累積保持・回数撤去・しきい値0.05)=7e718f5〜5c17d68。詳細は §7）_
