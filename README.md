# TASUKARU 介護AIアプリ — 開発引き継ぎ(ミニマム版)

> **最新更新: 2026-05-14 Session 37 完了(Phase 2.B 詳細設計フェーズ達成)**
> このファイルは「次セッションを始める Claude が最初に読むだけで仕事が始められる」ことを目的に**ミニマム化**してある。過去 Session の詳細ログは git history を `git log --all --oneline` で参照する。Session 33 までの累積 README は git の `tasukaru-dev` ブランチ履歴(`README.md` 旧版)に残っている。

---

## 0. 最初に必ず読む3点

1. このREADMEを末尾まで(短いはず)
2. `docs/SESSIONxx_HANDOFF.md` の最新版(直近セッションの引き継ぎ)
3. ユーザーから提示された当回タスクの仕様

---

## 1. プロジェクト基本情報(不変)

### サービス概要
- **TASUKARU**: 介護現場の「書く」負担をゼロにする AI アプリ
- マスコット: タスカルくん(レッサーパンダ/アライグマ風キャラ)
- 介護記録の音声入力、AIによる文章生成、バイタル管理、ケース記録、掲示板、利用者管理など

### 環境
| 環境 | Supabase プロジェクトID | Cloud Run | URL |
|---|---|---|---|
| **本番** | `abvglnkwtdeoaazyqwyd` | `tasukaru` (asia-northeast1) | `https://tasukaru-191764727533.asia-northeast1.run.app` |
| **dev** | `otjevnmoycnvaxeltrtj` | `tasukaru-dev` (asia-northeast1) | `https://tasukaru-dev-191764727533.asia-northeast1.run.app` |

### Git
- リポジトリ: `https://github.com/cocokaraplus-max/kaigo-ai-app`
- **本番ブランチ**: `tasukaru`(`cloudbuild.yaml` で自動デプロイ)
- **dev ブランチ**: `tasukaru-dev`(`cloudbuild-dev.yaml` で自動デプロイ)
- ローカル: `/Users/ZIMAX/.../kaigo-ai-app`(Mac、VSCode ターミナル)

### 施設(本番・dev 共通)
| facility_code | 用途 |
|---|---|
| `cocokaraplus-5526` | 本物の運用施設 |
| `DEMO001` | デモ施設 |
| `YOUR_FACILITY_CODE` | テスト施設 |

---

## 2. 絶対ルール(禁忌・厳守事項)

### 🚨 ブランチ事故防止(教訓 #29)
- ローカル作業中は**常に `tasukaru-dev` ブランチ**。VSCode 左下のブランチ表示を必ず確認
- 本番リリース時のみ `tasukaru` に切り替え、マージ&push したら**即座に `tasukaru-dev` に戻す**
- `git status` で「On branch tasukaru-dev」になっているか毎回確認

### 🚨 本番リリース順序厳守(教訓 #30)
**必ず DB → コード の順**。逆順は本番障害の元。
1. 本番 Supabase で DB 変更(`ALTER TABLE` / `INSERT INTO record_categories` など)
2. DB 変更の確認(SELECT で結果確認)
3. `git checkout tasukaru` → `git merge tasukaru-dev --no-ff` → `git push origin tasukaru`
4. Cloud Build 自動発火、本番デプロイ完了を待つ
5. iPhone で本番動作確認
6. `git checkout tasukaru-dev` でブランチ戻す

### 🚨 Supabase SQL Editor の使い方(教訓 #27)
- 長文 SQL + 日本語コメント + 絵文字を入れると AI 補完が暴走
- **1 文ずつ、短い英字主体の SQL** を実行
- 日本語値を入れる時は値だけ(`'休み連絡'` など)、コメントは別の場所で

### 🚨 CREATE TABLE 時(教訓 #28)
- 緑の「Run」ではなく、**中央に出る薄黄色「Run without RLS」が正解**
- 一度しか出ないので見逃さない

### 🚨 ファイル受領時のハッシュ照合(教訓 #32)
- ユーザーがファイルを添付してきたら、Chrome キャッシュ(`window._xxx`)の SHA-256 と必ず照合
- 一致しなかった場合、ローカルとリモートで差分がある可能性 → そのまま編集すると衝突
- `sha256sum` でハッシュ確認、Chrome 側は `crypto.subtle.digest('SHA-256', ...)` で計算して突合

### 🚨 やってはいけない
- 本番 DB に直接 DROP / TRUNCATE / 大量 DELETE
- 本番ブランチで直接コミット(必ず dev → マージ)
- dev で動作確認していない変更を本番にマージ
- カラム追加なしでコードに新カラム参照を入れる(順序逆転)

---

## 3. 作業の進め方(標準フロー)

### 通常タスク
1. ユーザーから仕様確認(必要なら Q&A 形式で詰める)
2. 影響範囲を grep / 既存コード閲覧で把握
3. dev に対して順に: DB変更 → コード変更 → push → Cloud Build 完了待ち → dev で動作確認
4. dev OK なら本番リリース手順(上記教訓 #30)に進む
5. README 更新 + 次回への SESSION_HANDOFF.md 作成

### ファイル編集の作法
1. ユーザーから VSCode 経由で対象ファイルを `cp ~/Desktop/xxx ./` で受領 → ハッシュ照合
2. Claude 側で str_replace で修正 → `/mnt/user-data/outputs/xxx` に書き出し
3. ユーザーが `present_files` でダウンロード → `cp ~/Desktop/xxx ./` で上書き
4. `git diff` で差分確認 → 想定通りなら add → commit → push

### push 前の最終チェック
- `git status` でブランチが `tasukaru-dev` か(本番作業時のみ `tasukaru`)
- modified が想定ファイルだけか(余計な変更が混ざってないか)
- `git diff | wc -l` で差分量が想定範囲内か

---

## 4. アプリの主要構造(おぼえておきたい)

### カテゴリ管理(2 層構造、重要)
- **`record_categories` テーブル**: 施設ごとに登録、**記録入力画面のカテゴリ選択**で使われる
- **`AIC_MANUAL_CATEGORIES` JS 配列**(`templates/daily_view.html`内ハードコード): **ケース記録の「カテゴリ変更」モーダル**で使われる。DB と独立。
- **`VALID_CATEGORIES` Python set**(`app.py` 内 2 箇所): API 側で受け付ける有効カテゴリのホワイトリスト
- **`AI_CATEGORY_DEFINITIONS` dict**(`utils.py` 内): AI 判定用のカテゴリ定義 + プロンプト
- **検索プルダウン**: `/api/records/search/categories` で `records` テーブル内の実使用カテゴリを動的取得(DB登録と無関係)

→ **カテゴリを増やす時は最低 4 箇所(または 5 箇所)同時更新が必要**。1 箇所でも漏れると挙動が乖離する。

### 現在のカテゴリ(Session 33 完了時点)
9 カテゴリ: 入浴 / 食事 / 排泄 / コミュニケーション / 心身状況 / 訓練状況 / ヒヤリハット / 休み連絡 / その他
- 「休み連絡」は Session 33 で追加。`leave_reporter_type` (self/family) と `leave_reporter_relation` (任意の文字列) を持つ
- ヒヤリハットは dev・本番ともに反映済み(Session 35 で dev に追加完了)

### Cloud Build トリガー
- `tasukaru` ブランチ push → `cloudbuild.yaml` 走行 → `tasukaru` Cloud Run
- `tasukaru-dev` ブランチ push → `cloudbuild-dev.yaml` 走行 → `tasukaru-dev` Cloud Run
- 平均 2〜5 分でデプロイ完了

### Chrome タブ構成(セッション開始時にあると便利)
- dev アプリ(daily_view または top)
- 本番アプリ(top)
- 本番 Cloud Logs
- 本番 Cloud Build
- dev Supabase SQL Editor
- 本番 Supabase SQL Editor

---

## 5. 教訓集(累積)

| # | 内容 |
|---|---|
| #27 | Supabase SQL Editor は長文+日本語コメントで AI 補完暴走 → 1 文ずつ短い英字主体 |
| #28 | CREATE TABLE 時は中央薄黄色「Run without RLS」が正解(緑ではない) |
| #29 | VSCode 左下ブランチは常に `tasukaru-dev`(本番作業時のみ一時的に `tasukaru`、終わり次第戻す) |
| #30 | 本番リリースは DB → コード の順序厳守 |
| #31 | daily_view のカテゴリ変更モーダルは JS ハードコード(`AIC_MANUAL_CATEGORIES`)、DB の `record_categories` とは別世界(Session 33) |
| #32 | ファイル受領時は SHA-256 で必ずハッシュ照合(Chrome キャッシュ vs 添付ファイル)。整合性確認なしに編集進めない(Session 33) |
| #33 | カテゴリ追加は最低 4-5 箇所同時更新が必要: `record_categories` テーブル / `AIC_MANUAL_CATEGORIES` 配列 / `VALID_CATEGORIES` set 2 箇所 / `AI_CATEGORY_DEFINITIONS` dict(Session 33) |
| #34 | 視覚的なズレを「数値変更で試行錯誤」しない。**実機の `getBoundingClientRect` で位置を実測**してから修正する。デバッグオーバーレイを画面に直接出す方式が iPhone Safari でも開発者ツール不要で確実(Session 34) |
| #35 | CSS の `bottom` 値の差 = **同サイズ要素の中心間距離**。要素サイズ補正は不要(Session 34、肉球配置で半径計算を間違えた経験から) |
| #36 | `position: fixed` 要素は CSS で**閉時の初期位置を明示**しないと、座標未指定でデフォルト位置(左上 or 元の HTML位置)に出る。アニメーション元位置として `bottom`/`right` を必ず指定する(Session 34、スピードダイヤルのラベルで発生) |
| #37 | ZIMAX さんの口頭/文字説明だけで UI の正確な配置を理解しない。**手書きスケッチ画像をもらうのが最も確実**。「肉球配置」のような具体的なメタファーが出たら即座に確認する(Session 34) |
| #38 | **ハンドオフ書の記載は鵜呑みにせず、現状確認 SELECT / git log / ハッシュ照合を最初に実行する**。ハンドオフ書とリポジトリ実態がズレている可能性は常にある(Session 35) |
| #39 | 左右別がある部位(`_l` / `_r`)は**本人視点(医療慣習)**で命名する。画面座標で `_l` を画面左にすると医療職と齟齬が出る(Session 36、VAS 部位 ID) |
| #40 | SVG ドラッグ UI で `pointerdown` イベント直後に DOM 要素を再生成するとブラウザの pointer capture が切れてドラッグが続かない。状態だけ変えて、再描画は `pointerup` まで遅延する(Session 36、ポリゴンエディタ) |
| #41 | 設計時の部位/項目リストは**最初に「臨床的に意味のある全部位」を機械的に列挙**。UI 都合で減らさない。後から追加するのは大変(Session 36、VAS 部位定義 54 箇所) |
| #42 | CSS `display: flex` を直接付けると HTML `hidden` 属性に勝つ。モーダル等で `hidden` 属性を有効にしたいときは **`:not([hidden])` セレクタ**を併用する。例: `.vas-modal:not([hidden]) { display: flex }`(Session 36、モーダル開きっぱなしバグ) |
| #43 | **iPhone モーダルは下端タブで隠れる**。Safari ホームバー + ナビバーで画面下 80-100px が覆われる。対策: モーダル overlay は `align-items: flex-start`(上寄せ)、カードに `margin-bottom: 80px`、アクションボタンは `position: sticky; bottom: 0` + `min-height: 44px`(iOS HIG)(Session 36、VAS 編集モーダル) |
| #44 | **手動構築 FormData の `append` 漏れに注意**。`new FormData()` で空を作り `formData.append(...)` で個別追加するパターンでは、フォームに新フィールドを追加したら JS 側も更新が必要。新フィールド追加時は `grep "formData.append" templates/xxx.html` で append 一覧を確認するクセを(Session 36、VAS データが保存されなかった原因) |
| #45 | **ハンドオフ書の「適用済み」記述を盲信せず、実 DB クエリで再確認**(教訓 #38 の拡張)。Session 35 → 36 → 37 と 3 連続で「適用済み」記述と実態のズレが発生している(Session 36) |
| #46 | **「新規実装」と決めた機能でも、必ず dev URL を Chrome MCP で開いて既存実装の有無を確認する**。Session 37 で Phase 2.B 着手前に `/assessment` を見たら既に動作中の実装があった。ハンドオフ書・設計書だけでは既存実装の存在に気付けないことがある(Session 37) |
| #47 | **HTML 内の DB 参照記述と実 DB スキーマは別検証**。`templates/assessment.html` に `{{ p.training_goal or '' }}` と書かれてるが、実 DB の `patients` テーブルには `training_goal` カラムが存在せず、常に空文字を返していた。HTML での参照を見ても DB の存在は保証されない(Session 37) |
| #48 | **設計フェーズと実装フェーズを明確に分ける、設計のみで 1 セッション使う価値がある**。Session 37 全体を Phase 2.B の設計に当てたことで、Session 38 でコード実装に迷いなく入れる土台ができた。急いで実装 → 仕様未確定で手戻り、より効率的(Session 37) |
| #49 | **介護保険制度の区分(要介護/要支援/事業対象者)で評価方式が変わる、UI も DB も区分対応で設計**。要介護=ICF三軸(心身機能・活動・参加)、要支援/事業対象者=単純に短期/長期目標達成のみ。評価フォームは区分によって動的に切り替わる(Session 37) |
| #50 | **「捨てる勇気」の設計判断**。既存データを CSV 保管後に廃止することで、汎用設計を獲得できる。Session 37 では旧 `assessments` テーブル(1 事業所のみ 77 件)を CSV 保管 → 廃止 → 22 項目構造化フォームで新規構築、と判断。データを引きずらない方が結果的にクリーン(Session 37) |
| #51 | **マスタデータの一元管理ビジョンを早期に組み込み、各画面の関数を「将来マスタ参照可」設計に**。`get_initial_training_goal()` 等の初期値取得関数を、マスタ未整備でも動く構造(優先順位: マスタ → 先月評価 → フォールバック)にしておけば、後でマスタ画面ができた時に関数の中身だけ差し替えれば全画面に反映される(Session 37) |

---

## 6. 直近セッションのサマリ(過去 2-3 件だけ)

### Session 37(2026-05-14)完了 — Phase 2.B 月次評価機能の詳細設計フェーズ達成 🎯

**コード変更なし。設計のみで全 12 論点を確定、Session 38 で実装に迷いなく着手できる土台を構築。**

#### A) 状況把握と教訓 #45 連発の発見
- ハンドオフ書には「dev・本番ともに `patient_evaluations` 未作成」と書かれていたが、実 DB 確認で **dev には既に 23 カラム + UNIQUE INDEX が完成済み**だった
- dev URL を Chrome MCP で開いたら、想定外に **既に `/assessment` 機能が動作中**だった(旧自由文+AI生成形式、`assessments` テーブル使用)→ 教訓 #46 として明文化
- `assessment.html` 内の `data-goal="{{ p.training_goal or '' }}"` は、実 DB の `patients` テーブルにカラムがなく常に空文字 → 教訓 #47 として明文化

#### B) ZIMAX さんの方針判断
- 旧 `assessments` テーブル(本番 77 件、cocokaraplus-5526 のみ使用)は CSV エクスポート保存後に廃止
- 「他事業所も使うことを考えると」 → 汎用設計を獲得(教訓 #50)
- 「カテゴリから生成」の意図は「月次評価」ではなく「ケアマネ報告書」用、評価は手動入力に純化
- 「利用者マスタを別途整備、CSV インポート/エクスポート対応」を Phase 2.D として宣言

#### C) Phase 2.B の確定設計(全 12 論点、詳細は `docs/SESSION38_HANDOFF.md`)
1. タブ構成: 2 タブ維持(新規評価/過去の評価)、中身置換
2. 利用者選択 UI: 既存流用
3. training_goal: `patient_evaluations.training_goal` カラム追加、先月の値を初期値、将来マスタ対応の関数設計
4. UI 構成: 5 セクション、アコーディオン折りたたみ(VAS と統一)
5. 初期開閉: 訓練目標のみ初期開
6. radio 選択肢: 達成/一部達成/未達成、満足度・適切性は記号付き
6-2. 介護区分: ハイブリッド(`patients.care_level` + `patient_evaluations.care_classification`、先月引き継ぎ + 将来マスタ参照)
7. 新規希望必須化: JS バリデーション + 確認ダイアログ
8. 保存ボタン: sticky 下端固定 + トースト + フォームリセット
9. 過去の評価表示: D-1(最小フィルタ)+ b(折りたたみ)+ 濃(全項目)+ 並び順切替可能
10. バリデーション: B 必須 + アラート + 3 色バッジ(緑/オレンジ/赤)+ 完成状態フィルタ + 評価者名 Y
11. 同月再保存: D 案(既存データ自動チェック → 通知 → 自動ロード)
11-2. 編集競合: 方式 3(悲観的ロック)、10 分タイムアウトで自動解除
12. テンプレ置換: A(`templates/assessment.html` を直接上書き)

#### D) Session 38 で実行する DDL(dev のみ、4 文)
```sql
ALTER TABLE public.patient_evaluations ADD COLUMN training_goal text;
ALTER TABLE public.patient_evaluations ADD COLUMN care_classification text CHECK (...);
ALTER TABLE public.patients ADD COLUMN care_level text CHECK (...);
ALTER TABLE public.patient_evaluations ADD COLUMN editing_by text;
ALTER TABLE public.patient_evaluations ADD COLUMN editing_started_at timestamptz;
```
→ `patient_evaluations` は 27 カラム、`patients` は 8 カラムに

#### E) Session 37 で新規発動の教訓
#46(新規実装前に既存実装確認)/ #47(HTML 参照と実 DB スキーマは別検証)/ #48(設計と実装フェーズ分離)/ #49(介護保険区分対応)/ #50(捨てる勇気)/ #51(マスタ未整備でも動く関数設計)

---

### Session 36(2026-05-13)完了 — Phase 2.A VAS 入力機能 実装・本番リリース 🎉

**dev + 本番両方リリース済み。iPhone 動作確認 OK。**

#### A) 実装内容
- 人体図画像 `static/img/body/body_front.png` `body_back.png` を配置
- `templates/_vas_widget.html`(852 行、SVG ポリゴン 54 部位 = 正面 31 + 背面 23、モーダル + 値選択 UI)
- `templates/input.html` に VAS ウィジェット組み込み(カテゴリ「心身状況」「訓練状況」選択時のみ表示、アコーディオン化)
- `app.py /input` POST:VAS データを `record_vas` テーブルに一括 INSERT
- `app.py daily_view`:`record_vas` を JOIN で取得 → 各 record に `vas_records` 添付
- `app.py /api/update_record`:VAS データの UPSERT(全削除 → 再 INSERT 戦略)
- `templates/daily_view.html`:記録カード下に**赤色 VAS 表示**(JS で部位 ID → 日本語ラベル変換)+ 編集モード共有モーダル

#### B) DB 状態
- **`record_vas` テーブル(8 カラム)**: **dev・本番両方適用済み** ✅
- `patient_evaluations` テーブル: **dev のみ作成済み(23 カラム + UNIQUE INDEX)、本番未作成**(Session 37 で発見、Phase 2.B 完成後の本番リリース時に本番にも適用予定)

#### C) 解決したバグ 3 件
1. モーダル開きっぱなし(commit `77bcae9`):CSS `display:flex` が HTML `hidden` 属性に勝った → `:not([hidden])` で防ぐ(教訓 #42)
2. VAS データ 0 件保存(commit `24d9aef`):`saveRecord()` の手動構築 FormData に `vas_records` の append が漏れていた。Chrome MCP `javascript_tool` で `saveRecord.toString()` を確認して判明(教訓 #44)
3. iPhone でモーダル確定ボタン押せない(commit `96f836b`):下端タブで「キャンセル」「確定」が隠れる → 上寄せ + sticky bottom + 下マージン(教訓 #43)

#### D) コミット履歴(Session 36 全体)
```
96f836b fix(vas): iPhone-friendly VAS edit modal (sticky bottom action buttons)
d89406d feat(vas): display + edit VAS records in daily_view (Session 36 Step 6)
24d9aef fix(vas): include vas_records in saveRecord FormData
56cf5dc feat(vas): persist VAS records + collapsible accordion UI (Session 36 Phase 2.A)
77bcae9 fix(vas): modal hidden attribute now respected (was overridden by display:flex)
cb25d97 feat(vas): add VAS widget for 心身状況/訓練状況 (Session 36 Phase 2.A WIP)
```
本番マージ: `4487148`(`bb7e681..4487148 tasukaru -> tasukaru`)

---

### Session 35(2026-05-12)完了 — 本番リリース確認 + dev ヒヤリハット追加 + 新規 3 機能の設計

**dev push 済み(設計ドキュメントのみ)、新規 3 機能のコード実装は Session 36 以降**

#### A) Session 34 の本番リリース確認(教訓 #38 発動)
ハンドオフ書では「未実施」だったが、git log で確認したところ既に完了済みだった(commit `fa01b06`)。

#### B) dev cocokaraplus-5526 にヒヤリハット追加(Session 33 持ち越し)
本番との CSV ハッシュ照合で完全一致確認(`f72641dd...`)。

#### C) 新規 3 機能の設計フェーズ
- 機能 1: VAS 入力機能(Phase 2.A、Session 36 で完成)
- 機能 2: 月次評価データ管理(Phase 2.B、Session 37 で詳細設計完成、Session 38 で実装予定)
- 機能 3: ケアマネ提出書類生成(Phase 2.C、Session 39 以降推奨)
- 設計詳細: `docs/CARE_MANAGER_REPORT_DESIGN.md` 参照

(Session 34 以前は git log を参照)

---

## 7. 既知の未対応事項(次セッション=Session 38 での対応候補)

### ✅ 完了: Phase 2.A VAS 入力機能(Session 36 で本番リリース達成)
### ✅ 完了: Phase 2.B 詳細設計(Session 37 で 12 論点全確定)

### 🟡 最優先: Phase 2.B コード実装(Session 38 推奨)
- Phase 2: DB 準備
  - **本番 `assessments` テーブル 77 件を CSV エクスポート**(Session 38 着手前必須、データ消失防止)
  - dev に DDL 4 文実行(`docs/SESSION38_HANDOFF.md` 参照)
- Phase 3: `templates/assessment.html` 全面書き換え(38 KB)
- Phase 4: `app.py` の /assessment route + 新 API 5 つ
- Phase 5: `evaluation_helper.py` 新規作成
- Phase 6: dev push + Cloud Build + iPhone 動作確認
- 詳細は `docs/SESSION38_HANDOFF.md` 参照

### 🟠 Session 39 以降
- dev 動作確認後、`assessments` テーブル DROP(dev)
- 本番 Supabase に DDL 4 文適用 + tasukaru ブランチへマージ
- 本番動作確認後、本番 `assessments` テーブル DROP
- Phase 2.C ケアマネ書類生成
- Phase 2.D 利用者マスタ整備(短期目標/長期目標/担当ケアマネ/介護度等の一元管理 + 既存介護ソフトからの CSV インポート)

### 🟢 余裕があれば
- AI 統合記録に VAS データを含める
- 月間 VAS グラフ(部位ごとの VAS 値推移を折れ線で表示)
- 印刷スタイル
- 作業用 HTML ファイル `vas_coordinates_editor.html` と `vas_polygon_editor_v2.html`(Untracked)の削除
- 旧 README(累積版、4216 行)の整理判断

---

## 8. 次セッション開始の標準シーケンス

```bash
# ローカルの状態確認
cd /Users/ZIMAX/.../kaigo-ai-app
git status                                # On branch tasukaru-dev であること
git pull origin tasukaru-dev              # 最新を取得
git log --oneline -5                      # 直近 5 commit を確認

# Chrome タブを開く(可能なら)
# - dev daily_view, 本番 top, 本番 Cloud Build, dev Supabase, 本番 Supabase

# このREADMEと docs/SESSION38_HANDOFF.md を Claude に提示
```

---

以上。これだけ読めば次セッションを始められる。詳細は git history + Supabase Dashboard で確認可能。
