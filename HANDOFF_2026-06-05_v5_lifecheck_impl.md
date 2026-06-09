# TASUKARU 開発 引き継ぎメモ（2026-06-05 v5：生活機能チェック 実装）

このメモは v4（タスク/掲示板の公開範囲）の続き。本セッションで生活機能チェック（様式3-2）を設計確定〜入力ページ実装まで大きく前進させた記録。**すべて DEV のみ。本番は未反映**（DEV確認が一通り済んでから DDL→コードの順で本番反映する）。

読む順序: v1 → v2 → v4 → 本v5 → README。（v3_lifecheck_design は存在しないことが判明。下記参照）

---

## 0. 最重要の設計判断（必読）

### 0-1. v3設計メモは存在しない
引き継ぎでは `HANDOFF_2026-06-05_v3_lifecheck_design.md` を読む前提だったが、ローカルに存在しなかった（`find`/`ls` で確認済み）。assist の詳細設計はこのメモには無いので、下記の本セッションでの決定を正とする。

### 0-2. 前任のDB設計と様式3-2の食い違いを発見し、データモデルを「理想形」に確定
- 前任は ADL を **Barthel点数の整数**で保存する設計だった（`_LIFE_ADL_FIELDS` が int）。
- しかし一次資料（厚労省様式3-2、文書 care.qlc-system.co.jp/Ace/article/vol.936-85.pdf 等）で確認した結果、**様式3-2の本来の評価は「自立/見守り/一部介助/全介助」の4段階＋課題有無**。Barthelは「参考に」する位置づけ。
- 一方、LIFE提出（個別機能訓練加算Ⅱ）ではADLをBarthel系で出す。
- HIRO と協議し **「理想形」= source of truth を項目ごとに最も正確な形で持つ** に決定:
  - **ADL10項目（Barthel対象）= Barthelの正式区分（点数 integer）を主データ**。点数→4段階は導出可能（逆は不可）なので情報量の多い点数を持つ。
  - **車椅子・IADL3・基本動作5 = 4段階レベル（text: independent/watch/partial/full）**。Barthel配点が無いため。
  - **全19項目に 課題有無(boolean) と 環境(text) と 状況メモ(text=既存_note)**。
- これにより、紙の様式3-2（4段階表示）も、LIFE提出（ADL点数）も、施設内推移も、1つの生データから導出できる。LIFE仕様が変わっても変換層で吸収。

### 0-3. Barthel正式配点（一次資料 厚労省 www.mhlw.go.jp/content/10900000/001622690.pdf）
ADL10項目の許容点数（これ以外の値は保存APIが弾く）:
- 食事 10/5/0、移乗 15/10/5/0、整容 5/0、トイレ動作 10/5/0、入浴 5/0、移動(歩行) 15/10/5/0、階段 10/5/0、更衣 10/5/0、排便 10/5/0、排尿 10/5/0。満点100点。
- 車椅子(adl_wheelchair)はBarthel対象外 → 点数でなく4段階で持つ。

### 0-3b. マスタ実データの判明事項（本セッション末で確認）
DEV Supabase の patient_profiles を確認した結果:
- **gender は全件 null**。性別を持つカラムは life_function_checks.gender と patient_profiles.gender のみ（後者は全null）。
- 患者マスタの性別登録は **patient_profile.html（384-388行）** で行い、保存値は **「女性」「男性」「その他」**（value もこの日本語）。
- そのため生活機能チェックの性別ドロップダウンを male/female から **女性/男性/その他** に統一（d1c0df3）。今後マスタに性別を登録すれば lcApplyMaster で自動入力が効く（コードは既に gender を読む実装）。
- care_level の実値は null / 事業対象者 / 要介護3 等。「事業対象者」がドロップダウンに無かったため追加（d1c0df3）。「要介護3」の利用者では介護度の自動入力が既に成功確認済み（仕組みは正常、入らなかったのは care_level=null の利用者だったため）。

### 0-4. LIFE提出CSVは保留（別紙Excel待ち・移行期）
- 個別機能訓練FORMのADLコード体系は「別紙_外部インターフェース項目一覧(3.00版).xlsx」にあり、Web検索でファイル取得不可（LIFEポータルからDL要）。
- かつLIFEは移行期（令和6年8月 新システム、令和8年5月 国保中央会移管）で仕様が流動的。
- よって**今は実装しない**。4段階＋点数を正しく貯めておけば、後で変換層を足すだけで対応できる設計にしてある。

---

## 1. DBスキーマ（DEV Supabase に適用済み・本番未適用）

テーブル `life_function_checks`（upsertキー: facility_code + patient_id + check_date）。
本セッションで以下を**追加適用**（SQL Editorで実行済み、冪等 ADD COLUMN IF NOT EXISTS）:
- `add_life_level_issue.sql`: 全19項目に `{item}_level`(text) と `{item}_issue`(boolean) を追加（38カラム）
- `add_life_env.sql`: 全19項目に `{item}_env`(text) を追加（19カラム）

最終構成（項目ごと）:
- ADL10: 点数(integer) + _level(未使用) + _issue + _env + _note
- 車椅子/IADL3/基本動作5: _level(使用) + 点数(未使用) + _issue + _env + _note
- メタ: visit_type, birth_date, gender, evaluator, evaluator_job, care_level, adl_independence, dementia_independence, note, staff_name 等

⚠️ DDLファイル（`add_life_level_issue.sql` / `add_life_env.sql`）は Downloads に保存された状態。リポジトリには未コミットの可能性。本番反映時に再実行が必要（本番Supabaseには未適用）。

---

## 2. 実装したもの（app.py / life_check.html）とコミット（dev）

| commit(dev) | 内容 |
|---|---|
| `f288abd` | /life_check ルート追加（骨組み: 利用者検索+評価日+履歴枠）+ 保存API拡張（Barthel検証/level/issue/env） |
| `e0cd26f` | life_check.html 完全版（全入力UI: Barthel区分ボタン/4段階/課題有無/環境/メモ/合計点/プリフィル/保存） |
| `eaa65e1` | UI改善: ADLボタン縦積み均等幅 / 合計バーをボトムナビ真上に固定（JS実測 --lc-nav-h） |
| `95bd466` | 基本情報の自動入力（患者マスタ優先: care_level/birth_date/gender） |
| `c183c45` | 過去評価の編集・削除（本人or管理者）+ 削除API /api/delete_life_check |
| `3bee65b` | 評価者をログイン職員名で初期化 + 職種ドロップダウン（5職種+その他自由入力） |
| `d1c0df3` | 性別selectをマスタ表記(女性/男性/その他)に統一 + 介護度に「事業対象者」追加。マーカー lc-gender-care-v1 |

### app.py の主な追加・変更（行番号は目安）
- 保存API `/api/save_life_check`（8924付近）を拡張。マーカー `life-save-expand-v1`。定数 `_LIFE_BARTHEL_ALLOWED`（ADL10の許容点数集合）、`_LIFE_LEVEL_FIELDS`（4段階項目）、`_LIFE_LEVEL_ALLOWED`、関数 `_life_level_or_none` / `_life_bool_or_none` / `_life_score_validated`。ADL10は点数検証、level項目は_level、全項目に_issue/_env。
- 取得API `/api/life_check_history`（9038付近）は `select("*")` で変更不要（新カラムも自動で返る）。
- 削除API `/api/delete_life_check`（9054付近）。マーカー `life-check-delete-api`。権限 = staff_name本人 or is_admin_user。
- ルート `/life_check`（8704付近、`life_check_page`）。マーカー `life-check-page-route`。render に my_name 追加（`life-evaluator-myname`）。

### life_check.html のマーカー
`lc-ui-fix-v1`（ボタン/合計バー）, `lc-master-prefill-v1`（マスタ自動入力）, `lc-edit-delete-v1`（編集削除）, `lc-evaljob-v1`（評価者/職種）。
- 入力状態は `lcState`、定義データ `LC_ADL`(Barthel正式ラベル) / `LC_LEVEL` / `LC_LEVELS`。
- 履歴は `window._lcHistMap`(id→record)。編集は `lcStartEdit`→`lcPrefill`（編集モード `_lcEditMode` でマスタガード無効化）。削除は `lcDeleteCheck`。
- 職種: select(`lc-evaluator_job_sel`)＋hidden/自由入力(`lc-evaluator_job`)。`lcJobChange`/`lcJobRestore`。保存値は職種名そのもの（「その他」の語は保存しない）。

### 保存実機確認: 済（DEVでHIROが保存成功を確認）

---

## 3. HIRO からの UI フィードバック（対応状況）
- ✅ 過去の編集・削除 → c183c45 で実装
- ✅ ボタンの大きさ不揃いで戸惑う → eaa65e1 でADLボタンを縦積み均等に（4段階は横並び維持）
- ✅ 合計バーが邪魔な位置 → eaa65e1 でボトムナビ(.bottom-nav 高さJS実測)の真上に固定配置
- ✅ 介護度/生年月日/性別をマスタから → 95bd466
- ✅ 自立度2種は前回値引き継ぎ → 既存プリフィルで対応
- ✅ 評価者を職員名から / 職種を選択式 → 3bee65b
- ✅ 介護度・性別がマスタ実データと整合（性別=女性/男性/その他、介護度に事業対象者）→ d1c0df3。性別はマスタが現状全null。patient_profile.html で登録すれば自動入力が効く。

---

## 4. 残作業（次セッション）

優先順の目安: A → B → C → D（EはExcel待ち）
- **A. assist API（AI相談）** ＝ 次にやる予定だった本題。仕様: 補助型（最終判定は職員）、出力JSON `basis`/`interpretation`/`candidate_levels`/`check_points`/`record_draft`。**項目ごと**に呼ぶ（フロントのAI相談ボタンは設置済み・現在は「近日対応予定」表示）。入力方式は**未確定**（案2=専用相談欄を推していた段階）。ADL項目は候補=Barthel区分、4段階項目は候補=4段階、と項目で出し分ける必要。雛形は app.py 4829-4880 の anthropic SDK 呼び出し（model='claude-sonnet-4-5'、content[0].text→フェンス除去→JSON）。別定数 `LIFE_ASSIST_PROMPT` を立てる。
- **B. 3か月アラート登録**: 保存時に check_date+3か月を `life_check_schedules`（scheduled_date, is_completed）に登録。TOP表示は新規実装。complete/snooze/delete は vital_recheck_schedules（app.py 2655-2759）のパターン流用。
- **C. 様式3-2出力**: 印刷用書類（4段階表示＋課題＋環境＋状況、ADLは点数も）。
- **D. LIFE CSV出力**: 別紙Excel入手後（保留）。
- **本番反映**: DEV確認が済んだら、本番Supabaseに2つのDDLを適用 → app.py/templates を本番マージ（DDL→コードの順）。

---

## 5. 注意・教訓（本セッションで再確認）
- **grepに日本語を使わない**（エンコードエラー。本セッションでも職種検索で文字化け発生）。英数字ID（lc-evaluator 等）で検索する。
- **アンカーは cat -et で空行確認**（保存API拡張で2ループ間の空行を見落としてcount=0で失敗 → 空行込みアンカーで解決）。同じく評価者/職種パッチで、UI修正が末尾に関数を足していたため `});\n</script>` アンカーが消えていた → `lcAdjustTotalBar` 閉じを含む末尾に修正。
- パッチは「全変更を組み立ててから最後に1回 write」設計なので、途中エラー時はファイル無傷（ロールバック）。
- present_files で出したファイルは、HIROがブラウザでDLしないと ~/Downloads に入らない（最初それで cp が No such file になった）。
- `.gitignore` で `HANDOFF*` 等が除外されている可能性（v4 が commit で nothing to commit になった）。本メモをコミットしたい場合は `git check-ignore -v <file>` で確認。

_最終更新: 2026-06-05（生活機能チェック: データモデル理想形確定＋DB拡張＋保存API＋入力ページ＋UI改善＋マスタ自動入力＋編集削除＋評価者/職種＋性別/介護度のマスタ整合。dev f288abd→d1c0df3。本番未反映。assist/アラート/様式出力/LIFE CSV が残）_
