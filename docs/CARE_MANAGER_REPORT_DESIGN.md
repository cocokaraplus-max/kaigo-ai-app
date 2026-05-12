# ケアマネジャー提出書類 + 関連機能 設計書

> **作成: 2026-05-12 Session 35 / 担当: ZIMAX + Claude**
> このドキュメントは Session 36 以降で実装する 3 つの新機能の設計をまとめたものです。
> 実装着手前に必ず最新版を読んでください。

---

## 0. 概要

Session 35 で議論・合意した内容を、Session 36 以降の実装フェーズで迷わず進められる形にまとめます。

### 作るもの 3 つ

1. **VAS 入力機能** — 疼痛尺度の構造化記録(人体図タップ式 UI)
2. **月次評価データ管理** — モニタリング標準項目の専用テーブル化
3. **ケアマネ提出書類生成機能** — 月次 PDF/Excel 出力

### なぜ作るのか

- **VAS**: 既存の介護記録は自由文中心で、疼痛の経時変化が定量化されていない。ケアマネへ「改善した」を数字で示せると説得力が出る
- **月次評価**: 既存モニタリングの一部項目(満足度等)は Excel テンプレに枠だけあり、DB に保存されず、Excel 出力後に手書きで二度手間になっている。これを DB 化する
- **ケアマネ書類**: 既存モニタリング(monitoring.html)は Excel 様式に合わせた帳票出力で、ケアマネに渡すには情報量が中途半端。視覚的にわかりやすい新書類を独自に作る

### 既存システムとの関係

```
[既存] records (日々の記録、カテゴリ別自由文)
[既存] patient_care_plans (長期/短期目標、支援内容)
[既存] /monitoring (Excel 出力、mappings/*.json で様式定義)

[新規] record_vas (VAS 入力、各記録に紐づく)
[新規] patient_evaluations (月次評価、月1行)
[新規] /care-manager-report (新規 PDF 書類生成画面)
```

新規 2 テーブルはどちらも **2026-05-12 時点で dev に作成済み** (commit: tasukaru-dev での DB 直接操作)。

---

## 1. VAS 入力機能

### 1.1 仕様

- VAS = Visual Analog Scale。0〜10 の整数(NRS タイプ)
- **表示カテゴリ**: 「心身状況」「訓練状況」の 2 カテゴリのみ。他カテゴリでは入力欄を表示しない
- **任意入力**: 痛みのない日は空欄で OK
- **部位**: 31 ポイント。詳細は §1.4
- **記録単位**: 部位 + 数値 + 体面(正面/背面)を複数記録可能
- **UI**: 人体図(illustAC 線画)上にタップで部位選択 → 数値選択モーダル → 図上に赤丸 + 下にリスト

### 1.2 DB スキーマ (record_vas)

```sql
CREATE TABLE record_vas (
  id BIGSERIAL PRIMARY KEY,
  record_id BIGINT NOT NULL,
  facility_code TEXT NOT NULL,
  user_name TEXT NOT NULL,
  part TEXT NOT NULL,
  side TEXT NOT NULL,
  vas_value SMALLINT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**設計判断**:
- `record_id` は親 records への参照、FK 制約はあえて付けない(削除カスケードを別途検討する余地を残す)
- `facility_code` `user_name` は非正規化(集計クエリで JOIN 不要にするため)
- `vas_value` の CHECK 制約は付けない(範囲変更の柔軟性、Python 側で検証)
- インデックスは Session 35 では作らない。Session 36 で実運用クエリを見てから判断
- Session 35-12 時点で **dev に作成済み**。本番未適用

### 1.3 UI 設計

#### 人体図

- 画像: illustAC 線画版(正面 / 背面、各 500×1000 PNG)
- 商用利用 OK 確認済み(illustAC 規約)
- 配置: Flask `static/img/body/body_front.png`, `body_back.png` に置く
- ハッシュ:
  - body_front.png: `43116441872c98b170765e7f3990b8f3b511f65cddd4fd088f590d11b140490d`
  - body_back.png: `d12b96d9a0d581d614e4db61d04056263f212305f5738cfce16fa3e83f52cd69`

#### タップ点座標(viewBox 250×500 基準)

`templates/_vas_widget.html` 内に JS 配列として持つ。

**FRONT (27 点)** (id, label, x, y):
- head (頭部) 125, 38
- neck (頚部) 125, 104
- shoulder_region_l/r (左肩部/右肩部) 95/155, 122
- shoulder_joint_l/r (左肩関節/右肩関節) 72/178, 130
- upper_arm_l/r (左上腕部/右上腕部) 62/188, 170
- elbow_l/r (左肘/右肘) 54/196, 215
- forearm_l/r (左前腕部/右前腕部) 46/204, 255
- wrist_l/r (左手関節/右手関節) 38/212, 300
- chest (胸部) 125, 160
- hip_joint_l/r (左股関節/右股関節) 107/143, 260
- thigh_l/r (左大腿部/右大腿部) 108/142, 320
- knee_joint_l/r (左膝関節/右膝関節) 110/140, 380
- lower_leg_l/r (左下腿部/右下腿部) 108/142, 425
- ankle_joint_l/r (左足関節/右足関節) 108/142, 465
- foot_l/r (左足部/右足部) 105/145, 485

**BACK (8 点)** (id, label, x, y):
- head_back (頭部後頭) 125, 38
- neck_back (頚部後頚) 125, 104
- upper_back (上背部) 125, 170
- lower_back (下背部・腰部) 125, 230
- thigh_l_back/r_back (左大腿部裏/右大腿部裏) 108/142, 320
- lower_leg_l_back/r_back (左下腿部裏/右下腿部裏) 108/142, 425

#### 操作フロー

1. 記録入力画面でカテゴリ「心身状況」「訓練状況」を選択した瞬間 VAS セクションが表示される
2. 人体図上のタップ点(灰色破線円)をタップ → 部位選択モーダル
3. モーダルに 0〜10 のボタンが表示(数値ごとに色: 0=灰、1-3=黄、4-6=橙、7-8=赤、9-10=濃赤)
4. 数値選択 → モーダル閉じる → 図上に色付き赤丸表示 + 下のリストに追加
5. リストは VAS 高い順にソート、各行に削除ボタン
6. 同じ部位を再タップで上書き可

#### 「医療用語化」(ZIMAX さんの要望)

- 自由文の本文は別途音声入力 → AI で医療用語化
- VAS のリスト(`左大腿部 VAS 5`)は構造化データなので、書類出力時にそのまま文字列化できる
- AI に「医療用語化」を頼む対象は本文のみ。VAS は AI を経由しない

### 1.4 影響範囲(教訓 #33 — Session 36 以降で同時更新)

新規:
- `static/img/body/body_front.png`, `body_back.png` (Flask static ディレクトリに配置)
- `templates/_vas_widget.html` (人体図 + JS、部分テンプレートとして他から include)

既存修正:
- `templates/record_input.html` (記録入力画面)
  - カテゴリ「心身状況」「訓練状況」選択時に VAS ウィジェットを表示
  - フォーム送信時に VAS データを JSON で同梱
- `app.py` の記録保存 API
  - records への INSERT に成功した直後、もらった VAS 配列を record_vas に INSERT (record_id 連携)
- `templates/daily_view.html` (ケース記録閲覧画面)
  - 該当記録に VAS データがあれば、簡易表示(`左大腿 VAS 5、腰 VAS 3`)

合計 5 ファイル(新規 2、既存 3)の同時更新が必要。

---

## 2. 月次評価データ管理

### 2.1 仕様

- 月 1 回、利用者ごとに 1 行の評価データを保存
- 既存モニタリング(`/monitoring`)とケアマネ書類(`/care-manager-report`)の両方で参照する共通データ
- 既存運用では Excel 出力後に手書きしていた項目を、システムで管理する
- 評価項目(22 個 + id + タイムスタンプ):
  - 識別: facility_code, user_name, year_month, evaluator_name
  - 測定値: weight_kg, attendance_count, attendance_target
  - 短期目標達成: short_goal_function/activity/participation_status
  - 長期目標達成: long_goal_function/activity/participation_status
  - 自由文(AI 整文対象): changes_by_training, issues_and_causes, special_notes
  - モニタリング 3 項目: new_requests_exist, new_requests_detail, satisfaction, service_appropriateness

### 2.2 DB スキーマ (patient_evaluations)

```sql
CREATE TABLE patient_evaluations (
  id BIGSERIAL PRIMARY KEY,
  facility_code TEXT NOT NULL,
  user_name TEXT NOT NULL,
  year_month TEXT NOT NULL,
  evaluator_name TEXT,
  weight_kg NUMERIC(5,2),
  attendance_count SMALLINT,
  attendance_target SMALLINT,
  short_goal_function_status TEXT,
  short_goal_activity_status TEXT,
  short_goal_participation_status TEXT,
  long_goal_function_status TEXT,
  long_goal_activity_status TEXT,
  long_goal_participation_status TEXT,
  changes_by_training TEXT,
  issues_and_causes TEXT,
  special_notes TEXT,
  new_requests_exist TEXT,
  new_requests_detail TEXT,
  satisfaction TEXT,
  service_appropriateness TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_patient_eval_user_month 
  ON patient_evaluations (facility_code, user_name, year_month);
```

**設計判断**:
- UNIQUE 制約あり(1利用者×1月×1評価が自然)
- `year_month` は TEXT (`'2026-04'` 形式)。検索しやすく、既存 monitoring_integration.py の year/month と親和性高い
- `satisfaction` `service_appropriateness` は `'○'` / `'△'` / `'✕'` のテキスト記号
- `new_requests_exist` は `'あり'` / `'なし'` のテキスト
- `*_status` (達成状況) は `'達成'` / `'一部達成'` / `'未達成'` のテキスト
- updated_at の自動更新は Trigger ではなくアプリ側で明示更新
- Session 35-12 時点で **dev に UNIQUE 制約含めて作成済み**。本番未適用

### 2.3 UI 設計

#### 新規画面: `/evaluations` (月次評価入力画面)

- 利用者選択 + 月選択 → 該当月の評価フォーム表示
- 既存データがあれば編集モード、なければ新規入力モード(UPSERT)
- 22 項目を 5 セクションに分けて配置(識別 / 測定 / 目標達成 / 自由文 / モニタリング3項目)
- 達成状況は radio ボタン(達成/一部達成/未達成)
- 満足度・適切性は radio ボタン(○/△/✕)
- 新規希望は radio (あり/なし) + テキストエリア(ありの場合に表示)
- 自由文 3 項目は textarea、AI 下書き生成ボタン付き(records から月内記録を取得して整文)

#### 入力タイミング(運用)

- 月末/月初の運用ルール(ZIMAX さん側で決定)
- 推奨: 月の最終利用日 or 月初 1 週目以内に職員が入力
- 一度入力した後でも月内なら何度でも修正可能(UPSERT で UPDATE される)

### 2.4 既存モニタリングとの統合方法

既存 `monitoring_integration.py` の改修:
- `api_monitoring_generate` で `collect_records_for_period()` 呼び出し後、`patient_evaluations` から該当月の評価を取得
- 取得した評価を `structured_data` にマージ(ケアプラン優先 → 評価優先 → AI 生成、の優先順位)
- AI には「これらの項目は埋まっているので、これに矛盾しない自由文を生成して」とプロンプト指示

### 2.5 影響範囲(教訓 #33)

新規:
- `templates/evaluation_input.html` (月次評価入力フォーム)
- `app.py` に新 route: `/evaluations` (GET 表示 / POST 保存)
- `app.py` に新 API: `/api/evaluations/<user>/<year_month>` (GET 取得 / POST 保存 / DELETE)
- `evaluation_helper.py` (新規モジュール、UPSERT ロジック等)

既存修正:
- `monitoring_integration.py` の `api_monitoring_generate`: 評価データを取り込むよう改修
- `monitoring_gen.py`: AI プロンプトに評価データ参照を追加
- `base.html` (ナビゲーション): 「月次評価」メニュー追加

合計 7 箇所の更新。

---

## 3. ケアマネ提出書類生成機能

### 3.1 仕様

- 月次、利用者単位
- A4 縦 1 ページ構成(連携依頼セクション削除版、Session 35 で合意)
- 出力形式: HTML 画面 → PDF(主) → Excel(将来)の優先順位

### 3.2 レイアウト確定版(案 A ベース)

Session 35 で確認した 3 案のうち **案 A(密集型 1 ページ)** を採用し、以下を変更:

- **削除**: ケアマネへの連携依頼セクション(ZIMAX さん指示)
- **保持**: ヘッダー、目標達成、推移グラフ 3 つ、カテゴリ別月次サマリ 6 個、支援内容と進捗

#### 1 ページ構成(上→下)

```
┌────────────────────────────────────────────────┐
│ ヘッダー: 利用者名、要介護度、対象期間、担当者     │
├────────────────────────────────────────────────┤
│ 目標と達成状況                                   │
│ ┌─ 短期目標 ─────────┬─ 長期目標 ───────────┐ │
│ │ 機能/活動/参加      │ 機能/活動/参加         │ │
│ │ 達成度バー          │ 期間進捗              │ │
│ └────────────────┴───────────────────┘ │
├────────────────────────────────────────────────┤
│ 推移グラフ(過去6か月)                          │
│ ┌─ 体重 ──┬─ 出席率 ──┬─ VAS推移 ──┐         │
│ │ 折れ線   │ 棒グラフ   │ 折れ線      │         │
│ └────┴─────┴──────┘         │
├────────────────────────────────────────────────┤
│ カテゴリ別月次サマリ(主要 6 カテゴリ)           │
│ 心身/訓練/コミュ/食事/排泄/入浴 × 各2-3行       │
├────────────────────────────────────────────────┤
│ 支援内容と進捗(①〜④)                          │
│ 進捗バー付き                                    │
└────────────────────────────────────────────────┘
```

詳細は Session 35 内で提示した SVG モック `care_manager_report_mockup_A` を参照(連携依頼セクションを除外したもの)。

### 3.3 出力形式

#### HTML 画面(まず作るもの)

- 新規 route `/care-manager-report`
- 利用者選択 + 月選択 → AI 下書き生成 → プレビュー画面(編集可能)
- 既存モニタリングの UI 構造を参考にする(`templates/monitoring.html` の検索 + 入力 + プレビューパターン)

#### PDF 出力(主目的)

- 候補ライブラリ: **WeasyPrint**(HTML/CSS から PDF を生成、日本語フォント対応良好)
- 代替: ReportLab(より低レベル、テキスト中心)
- 推奨: WeasyPrint
- 必要に応じて Cloud Run に WeasyPrint をインストール(Dockerfile 更新が必要、Session 36 で確認)

#### Excel 出力(将来拡張)

- 既存 `template_filler.py` の仕組みを流用
- 別途 mapping.json + xlsx テンプレを作成

### 3.4 データソース統合フロー

```
[ケアマネ書類生成]
       │
       ├─→ records から月内記録を取得 (カテゴリ別に整理)
       │   └─→ AI で各カテゴリ別月次サマリを生成
       │
       ├─→ patient_care_plans から目標・支援内容を取得
       │
       ├─→ patient_evaluations から月次評価を取得
       │   └─→ weight, attendance, *_status, 自由文等
       │
       ├─→ record_vas から月内 VAS データを取得
       │   └─→ 主訴部位を特定 + 月初→月末の変化を計算
       │
       └─→ 統合して structured_data を構築
              └─→ HTML テンプレに渡してレンダリング
              └─→ WeasyPrint で PDF 化
```

### 3.5 AI 生成戦略

- カテゴリ別サマリ: 1 回の Gemini 呼び出しで「6 カテゴリに分けて返して」と JSON で依頼(コスト/品質のバランス、案 A の選択)
- ただし「カテゴリ別の集計テキスト品質が低い」と判明したら、カテゴリごとに呼ぶ方式(N 倍コスト)に切り替え可能な構造で実装
- 既存 `monitoring_gen.py` の `_build_prompt` パターンを踏襲

### 3.6 将来拡張: 10 タイプの様式切り替え仕組み

事業所ごとにケアマネ提出様式が違うことに対応。既存の `monitoring_integration.py` パターンを踏襲:

```
mappings/
├── default/
│   └── care_manager_standard.json    ← 標準テンプレ
└── cocokaraplus-5526/
    └── care_manager_zimax.json       ← 自社カスタムテンプレ
```

`mapping.json` の中身:
- `template_id`: テンプレ識別子
- `layout_type`: `'compact_1page'` / `'narrative_2page'` / etc.
- `sections`: 表示するセクションの順序とオン/オフ
- `chart_types`: グラフ種類(線/棒)、対象データ

#### Session 35 時点でのスコープ

- まず **自社向け 1 テンプレ**を作る(自社運用 + 動作確認)
- 運用してニーズが見えたら 2 個目、3 個目と追加(段階的拡張)
- Session 35 で 10 個全部作るのは非現実的(教訓 #34 — 推測で広げない)

### 3.7 影響範囲(教訓 #33)

新規:
- `templates/care_manager_report.html` (画面 + プレビュー)
- `care_manager_report_gen.py` (新規モジュール、AI 整文 + データ統合)
- `mappings/<facility>/care_manager_standard.json` (自社向け様式定義)
- `app.py` に新 route 3 つ:
  - `GET /care-manager-report` (画面)
  - `POST /api/care-manager-report/generate` (AI 下書き生成)
  - `POST /api/care-manager-report/pdf` (PDF ダウンロード)
- (将来) `static/img/body/body_front.png` `body_back.png` (VAS 機能用、§1.3 で言及)
- `requirements.txt`: WeasyPrint 追加
- `Dockerfile`: WeasyPrint 依存ライブラリ(cairo, pango)追加

既存修正:
- `base.html` (ナビゲーション): 「ケアマネ書類」メニュー追加

合計 10 箇所以上の更新。**もっとも大規模な機能**。

---

## 4. Session 36 以降の実装計画

優先順位とリスクの整理:

### Phase 2.A: VAS 機能の実装(Session 36 推奨)

- DB は適用済み(record_vas)
- 必要作業: 人体図画像配置、_vas_widget.html 作成、記録入力画面改修、保存 API 改修、daily_view 改修
- リスク: 中(タップ座標のズレ、教訓 #34 の再発に注意。実機で測りながら調整)
- 期間目安: 4-6 時間

### Phase 2.B: 月次評価機能の実装(Session 37 推奨)

- DB は適用済み(patient_evaluations + UNIQUE)
- 必要作業: evaluation_input.html, 新 route, evaluation_helper.py, base.html ナビ追加, monitoring_integration.py 改修
- リスク: 低(独立性が高い、既存への影響少)
- 期間目安: 3-5 時間

### Phase 2.C: ケアマネ書類生成の実装(Session 38-39 推奨)

- DB は両方適用済み
- 必要作業: care_manager_report.html, care_manager_report_gen.py, mappings/*.json, 新 route 3 つ, WeasyPrint 導入, ナビ追加
- リスク: 高(WeasyPrint の Cloud Run 動作、日本語フォント、AI プロンプト品質、レイアウト調整、PDF レンダリング差異)
- 期間目安: 6-10 時間(2 セッションに分けるのが現実的)

### 実装順序の理由

- VAS が先: 月次評価 + ケアマネ書類が VAS データに依存するため、先に作って蓄積を始める
- 月次評価が次: ケアマネ書類のデータソースとして必要
- ケアマネ書類が最後: 最も大規模、上 2 つに依存

### 本番リリース戦略

- 各 Phase ごとに **dev で動作確認 → 本番リリース** のサイクル
- Phase 2.A から開始するときは:
  1. 本番 Supabase に DB スキーマ適用(教訓 #30 の DB→コード順)
  2. dev で実装テスト
  3. コードを tasukaru ブランチにマージ → push → Cloud Build → 本番デプロイ
  4. tasukaru-dev に戻す(教訓 #29)

---

## 5. 適用済み教訓のサマリ(Session 35 中の発動・新規)

### Session 35 中に発動した既存教訓

| # | 内容 | Session 35 での適用 |
|---|---|---|
| #27 | Supabase SQL Editor は 1 文ずつ短い英字 | CREATE TABLE / CREATE INDEX を 1 文ずつ実行 |
| #28 | CREATE TABLE は中央薄黄色「Run without RLS」 | record_vas, patient_evaluations 作成時に発動 |
| #29 | ブランチは常に tasukaru-dev、本番作業時のみ tasukaru | ドキュメント push 後に即時戻し済み |
| #30 | 本番リリースは DB → コード順 | DB だけ dev に適用、本番未触り |
| #32 | ファイル受領時は SHA-256 で照合 | 全添付ファイル(README, HANDOFF, monitoring.html 等)で実施 |
| #33 | カテゴリ追加は 4-5 箇所同時更新 | VAS/評価機能でも複数箇所同時更新が必要と認識 |
| #34 | 視覚的ズレは実測する | 人体図モック v1→v2→v3→v4 で段階的調整 |
| #37 | 手書きスケッチが最強 | ZIMAX 提供の人体図画像で方向性確定 |

### Session 35 で新規追加した教訓

#### 教訓 #38 候補(Claude 提案):
> **ハンドオフ書の「未着手タスク」は鵜呑みにせず、現状確認 SELECT / git log / ハッシュ照合を最初に実行する。ハンドオフ書とリポジトリ実態がズレている可能性は常にある。**

Session 35 での具体例 3 件:
1. Session 34 の本番リリースが「未実施」とハンドオフ書にあったが、実際は完了済みだった
2. dev `cocokaraplus-5526` ヒヤリハットが「未追加」とあったが、実際は追加済みだった
3. `record_vas` テーブル CREATE 時に「Success」が出たが、実際のスキーマは設計と違っていた(原因不明、SQL Editor の autocomplete 暴走疑い)

→ 全件、最初に SELECT/git log/ハッシュ照合で確認したから事故を防げた

---

## 6. 参考: Session 35 で固めたデータ・成果物

### dev Supabase の状態(2026-05-12 時点)

- `record_vas` テーブル作成済み、データなし
- `patient_evaluations` テーブル作成済み + UNIQUE 制約済み、データなし
- どちらも本番未適用

### 確認用 SHA-256(教訓 #32 履歴)

| 対象 | SHA-256 |
|---|---|
| README.md | `8153dae37f058fbdccec63b3eb9fbe644002b1e005a1b85726131c91c66f4201` |
| SESSION35_HANDOFF.md | `8f149f5812dc0c5442e5e812d2ede5a607a80acc4e831fbde9dfc71ac768b9c7` |
| body_front.png | `43116441872c98b170765e7f3990b8f3b511f65cddd4fd088f590d11b140490d` |
| body_back.png | `d12b96d9a0d581d614e4db61d04056263f212305f5738cfce16fa3e83f52cd69` |

### Session 35 で参照した既存ファイル(参考読み込み済み)

- `monitoring_integration.py` (Stage2 対応版、9.8K)
- `monitoring_gen.py` (Gemini 版、4K)
- `templates/monitoring.html` (18K)
- `template_filler.py` (4K)
- `excel_importer.py` (12K)

これらの理解を踏まえて新機能を設計したが、Session 36 で実装する際は最新版を読み直すこと(教訓 #32 で照合)。

---

## 7. 未決事項・宿題(Session 36 開始時に確認)

- [ ] 本番 Supabase への record_vas / patient_evaluations 適用タイミング(Phase 2.A の着手前)
- [ ] VAS の AI 医療用語化のプロンプト設計
- [ ] WeasyPrint の日本語フォント設定(Noto Sans CJK 等の組み込み)
- [ ] Cloud Run の Dockerfile で WeasyPrint 依存(cairo, pango)を入れた場合のビルド時間・イメージサイズ影響
- [ ] 評価データ未入力時、ケアマネ書類で「未評価」と表示するか空欄にするか
- [ ] 「あり」を選んだ際の `new_requests_detail` 必須化(アプリ側 or DB CHECK 制約)
- [ ] 10 様式テンプレートの 2 つ目を作る判断基準(運用ニーズが見えてから)

---

以上が Session 35 で固めた設計です。実装に入る前にこのドキュメントを最後まで読み、不明点を ZIMAX さんと確認すること。
