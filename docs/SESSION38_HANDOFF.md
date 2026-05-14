# SESSION 38 ハンドオフ書

> **前 Session: 37 / 作成: 2026-05-14 / 担当: ZIMAX + Claude**
> このハンドオフ書を最初に読んで、現状確認から始めること(教訓 #38, #45 厳守)。

---

## 🎯 Session 37 の成果

**Phase 2.B(月次評価機能)の詳細設計フェーズを完了 ✅**

全 12 論点を丁寧に詰め、Session 38 でコード実装に**迷いなく着手できる土台**を構築。
コード変更はまだなし(設計のみ、git に変更コミットなし)。

---

## ⚠️ Session 38 着手前にやること(教訓 #38, #45 厳守)

### 1. ブランチ確認

```bash
cd "/Users/ZIMAX 1/dev/kaigo-ai-app"
git status
git branch --show-current
git log --oneline -7
```

期待:
- ブランチ: `tasukaru-dev`
- 直近 commit 先頭: Session 37 のクロージングコミット(README + SESSION38_HANDOFF.md)
- その下: `c60397e docs: Session 36 reflect...`

### 2. DB 状態確認

```sql
-- dev で 1 文ずつ実行(教訓 #27)
SELECT count(*) FROM information_schema.columns WHERE table_name = 'patient_evaluations';
```
期待: **23**(Session 38 で DDL 追加するとここから増える)

```sql
SELECT count(*) FROM information_schema.columns WHERE table_name = 'patients';
```
期待: **7**(Session 38 で DDL 追加で 8 に)

```sql
SELECT count(*) FROM assessments;
```
期待: dev **0**、本番 **77**(`cocokaraplus-5526`)

### 3. 既存 /assessment 機能を確認

dev URL: `https://tasukaru-dev-191764727533.asia-northeast1.run.app/assessment`

これは **Session 38 で全面書き換え対象**。現状は旧自由文+AI生成形式。

---

## 📋 Session 37 で確定した全 12 論点(設計)

| # | 論点 | 確定内容 |
|---|---|---|
| 1 | タブ構成 | 2 タブ維持(新規評価/過去の評価)、中身置換 |
| 2 | 利用者選択 UI | 既存流用(動的フィルタ + 候補リスト + バッジ表示) |
| 3 | training_goal | `patient_evaluations.training_goal` カラム追加、先月の値を初期値、将来マスタ対応の関数設計 |
| 4 | UI 構成 | 5 セクション、アコーディオン折りたたみ(VAS と統一) |
| 5 | 初期開閉 | 訓練目標のみ初期開、他 4 セクション閉 |
| 6 | radio 選択肢 | 達成/一部達成/未達成 で統一、満足度・適切性は記号付き |
| 6-2 | 介護区分 | ハイブリッド方式(patients.care_level + patient_evaluations.care_classification、先月引き継ぎ + 将来マスタ参照) |
| 7 | 新規希望必須化 | JS バリデーション + 確認ダイアログ「詳細欄が空ですが、このまま保存しますか?」 |
| 8 | 保存ボタン | sticky 下端固定 + トースト + フォームリセット |
| 9 | 過去の評価表示 | D-1(最小フィルタ:利用者+対象月範囲)+ b(折りたたみ「絞り込み ▼」)+ 濃(全項目表示)+ 並び順切替可能(月降順/月昇順/利用者名/最終編集) |
| 10 | バリデーション | B 必須(利用者・対象月・介護区分・評価者・訓練目標)+ アラート + 3 色バッジ(緑/オレンジ/赤)+ 完成状態フィルタ + 評価者名 Y(自動セット + 編集可) |
| 11 | 同月再保存 | D 案(既存データ自動チェック → 通知「○月の評価は既に存在します。読み込みますか?」→ 自動ロード) |
| 11-2 | 編集競合 | 方式 3(悲観的ロック)、10 分タイムアウトで自動解除 |
| 12 | テンプレ置換 | A(`templates/assessment.html` を直接上書き、git で履歴管理) |

---

## 🗄 必須 DDL(Session 38 で dev に実行、4 文)

dev Supabase SQL Editor で **1 文ずつ実行**(教訓 #27、autocomplete 暴走対策):

```sql
ALTER TABLE public.patient_evaluations ADD COLUMN training_goal text;
```

```sql
ALTER TABLE public.patient_evaluations ADD COLUMN care_classification text
  CHECK (care_classification IS NULL OR care_classification IN ('要介護', '要支援', '事業対象者'));
```

```sql
ALTER TABLE public.patients ADD COLUMN care_level text
  CHECK (care_level IS NULL OR care_level IN (
    '要介護1', '要介護2', '要介護3', '要介護4', '要介護5',
    '要支援1', '要支援2', '事業対象者', '自立'
  ));
```

```sql
ALTER TABLE public.patient_evaluations ADD COLUMN editing_by text;
```

```sql
ALTER TABLE public.patient_evaluations ADD COLUMN editing_started_at timestamptz;
```

実行後の期待スキーマ:
- `patient_evaluations`: **27 カラム**(元 23 + training_goal + care_classification + editing_by + editing_started_at)
- `patients`: **8 カラム**(元 7 + care_level)

実行後に確認:
```sql
SELECT count(*) FROM information_schema.columns WHERE table_name = 'patient_evaluations';
-- → 27
```

```sql
SELECT count(*) FROM information_schema.columns WHERE table_name = 'patients';
-- → 8
```

---

## 🚀 Session 38 でやること(Phase 2-6)

### Phase 2: DB 準備 + データ保全

1. **本番 `assessments` テーブルを CSV エクスポート**(本番 77 件、データ消失防止)
   - Supabase Table Editor → assessments → Export CSV
   - ZIMAX さんの PC にローカル保存 + クラウド(Google Drive 等)にバックアップ
   - これは Session 38 で本番リリース前の必須前提

2. **dev に DDL 4 文実行**(上記 DDL リスト)

3. **動作確認**: dev で `SELECT * FROM patient_evaluations LIMIT 1;` がエラーなく通ること

### Phase 3: `templates/assessment.html` 全面書き換え(2-3 時間)

- 既存 38 KB(785 行)を 22 項目フォーム + 過去の評価フィルタ機能に置換
- 5 セクションのアコーディオン(訓練目標のみ初期開)
- sticky 下端保存ボタン
- 介護区分 selector で UI 分岐(要介護 = ICF三軸、要支援/事業対象者 = 単純)
- 既存 jQuery/JS スタイルとの一貫性維持

**注意点:**
- VAS ウィジェット(`_vas_widget.html`)の UI スタイルを参考にすること
- 教訓 #43 厳守: モーダルや sticky 要素は iPhone 下端タブで隠れないように
- 教訓 #44 厳守: `saveRecord()` 系で FormData 手動構築する場合、新フィールド全部 append
- 教訓 #42 厳守: モーダルは `:not([hidden])` セレクタで CSS の `display: flex` 上書き

### Phase 4: `app.py` の route + 新 API(1-2 時間)

**削除する既存 API**(app.py L2954-3084):
- `/api/generate_assessment`
- `/api/save_assessment`
- `/api/get_assessment`
- `/api/parse_assessment_file`

**新規追加する API**:
- `POST /api/save_patient_evaluation`(UPSERT、editing_by チェック)
- `GET /api/get_patient_evaluations`(過去一覧、フィルタ+ソート対応)
- `GET /api/get_patient_evaluation?user_name=&year_month=`(同月既存チェック、自動ロード用)
- `POST /api/acquire_edit_lock`(編集開始時に呼ぶ、10分タイムアウト判定)
- `POST /api/release_edit_lock`(保存完了 or キャンセル時)

**改修する route**:
- `GET /assessment`: `assessments.assessments` テーブル参照を **`patient_evaluations` テーブル**参照に変更、Jinja2 に渡すデータ構造変更

### Phase 5: `evaluation_helper.py` 作成(30-60 分)

以下の関数を含む新規モジュール:

```python
def get_initial_training_goal(facility_code, user_name, target_month) -> str:
    """訓練目標の初期値を返す。
    優先順位:
    1. (将来) patients.training_goal(マスタ、現状未実装)
    2. 対象月より前の最新 patient_evaluations.training_goal
    3. フォールバック: 空文字
    """

def get_initial_care_classification(facility_code, user_name, target_month) -> str:
    """介護区分の初期値を返す。
    優先順位:
    1. patients.care_level → care_classification にマッピング
       (要介護1-5 → '要介護'、要支援1-2 → '要支援'、事業対象者 → '事業対象者')
    2. 対象月より前の最新 patient_evaluations.care_classification
    3. フォールバック: 空文字
    """

def acquire_edit_lock(evaluation_id, current_user) -> dict:
    """編集ロックを取得。
    - 10 分以内に別ユーザーがロック中なら success=False を返す
    - タイムアウト or 自分のロックなら更新して取得
    """

def release_edit_lock(evaluation_id, current_user):
    """編集ロックを解放(自分が保持している場合のみ)"""

def evaluation_status(eval_dict) -> str:
    """評価レコードの完成状態を判定。
    - 'complete_green': 全項目入力済み
    - 'warning_orange': 必須以外が一部未入力(missing count を返す)
    - 'error_red': 必須項目未入力(理論上発生しない)
    """

def upsert_patient_evaluation(data: dict) -> dict:
    """評価データを UPSERT。
    - UNIQUE INDEX uq_patient_eval_user_month で同月既存判定
    - 既存ありなら editing_by が自分のロックか確認、UPDATE
    - 既存なしなら INSERT
    """
```

### Phase 6: dev push + Cloud Build + 動作確認(30-60 分)

1. `git add` → `git commit -m "feat(eval): Phase 2.B monthly evaluation form (Session 38 Phase 3-5)"`
2. `git push origin tasukaru-dev`
3. Cloud Build 完了待機
4. iPhone 実機で dev URL を開いて動作確認(教訓 #34):
   - 新規評価で 22 項目すべて入力できるか
   - 介護区分切替で UI が動的に変わるか
   - 訓練目標が先月の値を引き継いでいるか(初回は空でも OK)
   - 保存ボタン押下でトースト表示 → フォームリセット
   - 過去の評価タブで一覧表示、フィルタ動作
   - 同月再保存で「読み込みますか?」確認 → 自動ロード
   - 編集競合チェック(別ブラウザで同じ評価を開いてみる)

---

## 📌 Session 39 以降の計画(覚書)

**Session 38 では触らない:**
- 旧 `assessments` テーブルの DROP(dev も本番も保留)
- 本番リリース(本番 DDL → 本番コード push)

**Session 39 でやる:**
- dev で十分動作確認後、`assessments` テーブル DROP(dev)
- 本番 Supabase に DDL 4 文適用
- tasukaru-dev → tasukaru マージ → push
- 本番 Cloud Build → iPhone 実機確認(教訓 #34)
- 本番 `assessments` テーブル DROP(エクスポート確認後)

**Phase 2.D(将来、Session 40 以降?):利用者マスタ整備**
- `patients` テーブルにカラム多数追加(短期目標、長期目標、担当ケアマネ、介護度詳細など)
- 利用者マスタ画面の新規作成(専用 route + テンプレ)
- **既存介護ソフトからの CSV インポート機能**(ZIMAX さん要望、超重要)
- CSV エクスポート機能(双方向連携)
- 評価画面の `get_initial_*` 関数を「マスタ参照優先」に切替

---

## 🧠 Session 37 で発動した新規教訓(#46〜#51)

### #46 — 「新規実装」と決めた機能でも、必ず dev URL を Chrome MCP で開いて既存実装の有無を確認する
Phase 2.B 着手前に Chrome MCP で `/assessment` を見たことで、既に動作中の実装があると分かった。
ハンドオフ書・設計書だけでは既存実装の存在に気付けないことがある。

### #47 — DB に「事前に作られていた」テーブルでも、実際にアプリで参照されているか別途確認
既存 `assessment.html` の `data-goal="{{ p.training_goal or '' }}"` は、実は `patients` テーブルに
`training_goal` カラムがなく常に空文字を返していた。HTML での参照と実 DB スキーマは別に検証する。

### #48 — 設計フェーズと実装フェーズを明確に分ける、設計のみで 1 セッション使う価値がある
Session 37 全体を Phase 1(設計)に当てたことで、Session 38 でコード実装に迷いなく入れる。
急いで実装に入る → 仕様が固まらず手戻り発生、よりはるかに効率的。

### #49 — 介護保険制度の区分(要介護/要支援/事業対象者)で評価方式が変わる、UI も DB も区分対応で設計
要介護: ICF三軸(心身機能・活動・参加)で評価。要支援/事業対象者: 単純に「長期目標達成」「短期目標達成」。
評価フォームは区分によって UI が動的に切り替わる必要がある。

### #50 — 「捨てる勇気」の設計判断:既存データを CSV 保管後に廃止することで、汎用設計を獲得
既存 `assessments` テーブルは ZIMAX さんの 1 事業所(cocokaraplus-5526)で 77 件のみ。
他事業所展開を見据え、CSV エクスポート後に廃止 → 22 項目構造化フォームで新規構築。
データを引きずらない方が、結果的にクリーンで保守性が高くなる。

### #51 — マスタデータの一元管理ビジョンを早期に組み込み、各画面の関数を「将来マスタ参照可」設計に
training_goal、care_classification の初期値関数を、マスタ未整備でも動く構造にしておく
(`get_initial_training_goal()` 等)。Phase 2.D でマスタ画面ができた時、関数の中身だけ差し替えれば
全画面に反映される。

---

## 🔧 環境メモ

| 環境 | Supabase プロジェクト | Cloud Run | URL |
|---|---|---|---|
| **本番** | `abvglnkwtdeoaazyqwyd` | `tasukaru` | https://tasukaru-191764727533.asia-northeast1.run.app |
| **dev** | `otjevnmoycnvaxeltrtj` | `tasukaru-dev` | https://tasukaru-dev-191764727533.asia-northeast1.run.app |

### Git ブランチ運用(教訓 #29 厳守)

- ローカル作業: **常に `tasukaru-dev`** で commit
- 本番リリース: `tasukaru` に切り替え → `git merge tasukaru-dev` → `git push origin tasukaru` → **即座に `git checkout tasukaru-dev`** で戻る

### 本番リリース順序(教訓 #30 厳守、Session 39)

1. 本番 `assessments` を CSV エクスポート保全
2. 本番 Supabase に DDL 4 文適用
3. tasukaru ブランチへコードマージ・push
4. Cloud Build 完了確認
5. iPhone で実機動作確認(教訓 #34)
6. `tasukaru-dev` に即座に戻る
7. 後日、本番 `assessments` テーブル DROP

---

## 🧠 重要な教訓の再確認(Session 38 で意識すべきもの)

| 番号 | 内容 |
|---|---|
| **#27** | Supabase SQL Editor の autocomplete は時々暴走。コード貼り直しで対処、1 文ずつ実行 |
| **#28** | `CREATE TABLE` 時は `IF NOT EXISTS` を付ける |
| **#29** | 作業中は常に `tasukaru-dev`、本番マージ後すぐ戻る |
| **#30** | 本番リリースは DB → コード順厳守 |
| **#32** | ファイル受領時は必ずハッシュ照合 |
| **#34** | iPhone 実機で必ず最終確認 |
| **#38** | ハンドオフ書を盲信せず、実コード・実 DB で確認 |
| **#42** | `display: flex` は `hidden` 属性に勝つ、`:not([hidden])` で対処 |
| **#43** | iPhone モーダルは下端タブで隠れる、`position: sticky; bottom: 0` で対処 |
| **#44** | 手動 FormData の append 漏れに注意、`grep "formData.append" templates/*.html` で確認 |
| **#45** | ハンドオフ書の「適用済み」記述は実 DB で再確認 |
| **#46** | 「新規実装」前に Chrome MCP で既存実装の有無を確認 |
| **#47** | HTML での DB 参照と実 DB スキーマは別検証 |
| **#48** | 設計フェーズと実装フェーズを分ける |
| **#49** | 介護保険制度の区分対応(要介護/要支援/事業対象者) |
| **#50** | 「捨てる勇気」の設計判断 |
| **#51** | マスタ未整備でも動く「将来拡張可能な関数」設計 |

---

## 📂 主要ファイルと現状ハッシュ(Session 37 終了時点)

| ファイル | 行数 | ハッシュ | 用途 |
|---|---|---|---|
| `app.py` | 5827 | `0ebb681050636f7db839c82480d1d333d5a5c7e793a37a423851060d89996d9d` | route + API |
| `templates/assessment.html` | 785 | `7082774c82d5b63078c11aba79c053c237238f3da606d63da2f8ddee828fc3b3` | Session 38 で全面書き換え |
| `templates/base.html` | 2216 | 未取得 | ナビ追加不要(評価リンク既存) |
| `templates/daily_view.html` | 3056 | `3207fab653f8c6fcbcadfd08ea2df794bde874b4756379c89d405e49c88af01a` | 変更なし |
| `monitoring_integration.py` | 270 | 未取得 | Phase 2.C で改修 |

---

## ✅ Session 38 開始時のチェックリスト

- [ ] ブランチ `tasukaru-dev`、working tree clean(教訓 #29)
- [ ] dev DB のカラム数確認(patient_evaluations=23、patients=7)(教訓 #45)
- [ ] dev `/assessment` URL を Chrome MCP で開いて旧画面確認(教訓 #46)
- [ ] このハンドオフ書を末尾まで読み終わる
- [ ] **本番 assessments テーブル 77 件を CSV エクスポート**(これは Session 38 着手前に必須)

---

**Session 37 完了 / Phase 2.B 詳細設計フェーズ達成 🎉**
**Session 38 へ — 設計どおりに、迷いなく実装を!**
