# SESSION 66 HANDOFF — バイタル「本日の利用者を追加」が効かない問題の解決／シート読み取り／トースト

作成: 2026-08-18 / ブランチ: tasukaru-dev
本番tip: `83f6aef` / DEV tip: `2317f6d`

---

## ★★ 最重要：次に調査する人が必ず知っておくこと ★★

### 本番の施設コードは `cocokaraplus-5526`（`cocokaraplus` ではない）
今回、私は `facility_code = 'cocokaraplus'` で診断SQLを書き、**「0件」という結果を3回続けて誤った証拠として扱った**。
条件が合わずに0件だっただけで、実際にはデータが存在していた。**原因究明が大幅に遠回りになった。**

→ **診断SQLを書く前に必ず施設コードを確認すること。**
```sql
select facility_code, count(*) from patient_profiles group by 1 order by 2 desc;
```

### 利用者IDが2系統ある（混同するとデータが迷子になる）
| 用途 | 使うID | 型 | 例 |
|---|---|---|---|
| 画面の利用者一覧 / `vital_daily_excludes` / `vital_daily_includes` | `patient_profiles.id` | **UUID** | `06d9dcf6-a0c1-...` |
| `patient_visit_days`（曜日設定） / `vitals` | `patients.id` | **整数** | `13` |

- `get_patients()` は両方を返す：`id`（profiles/UUID）と `patient_int_id`（patients/整数）。
- 曜日設定UIは `{{ p.patient_int_id or p.id }}` を送る（正しい）。
- **バイタルの追加モーダルは `p.id`（UUID）を送っていた**（誤り）→ 誰も読まない行が量産されていた。

### `nth_per_day`（第N週指定）は表示直前に強制上書きする
`/vitals` は画面を組む直前にこうしている。**DBに何が入っていても関係なく非表示になる。**
```python
if not visit_nth_ok(p["nth_per_day"], _today_wd, today):
    p["weekdays"] = str(p["weekdays"]).replace(str(_today_wd), "")
    apd[str(_today_wd)] = "NONE"
```
→ 「追加したのに出ない」の**主因**。曜日設定を書き換えるアプローチでは絶対に解決しない。

---

## 発端（現場からの報告）
バイタルのページで「本日の利用者を追加」をしても利用者が表示されない。
追加した端末では一時的に出るが、**リロードすると消える**。他の端末では最初から出ない。

対象は **長松軒茂子さん**（`patients.id = 13`）。

## 実データ（本番・cocokaraplus-5526）
```
patients.id=13 の patient_visit_days:
  weekdays     = "24"                    → 火曜・木曜
  ampm_per_day = {"2":"AM", "4":"AM"}    → どちらも午前のみ
  nth_per_day  = {"2": 2}                → 火曜は「第2火曜」だけ
```
報告日 2026-08-18 は **第3火曜**（8/4=第1, 8/11=第2, 8/18=第3）。
→ `visit_nth_ok` が False → 表示直前に `NONE` へ上書き → **何度追加しても出ない**。

また、`patient_id` が UUID の**孤児行が9件**見つかった（追加モーダルの誤ったIDによる書き込み痕跡）。
読まれないだけで害は無いため、今回は削除していない。整理する場合は下記。
```sql
-- 孤児行の確認（削除前に必ず中身を見る）
select vd.* from patient_visit_days vd
left join patients p on p.facility_code = vd.facility_code and p.id::text = vd.patient_id::text
where vd.facility_code = 'cocokaraplus-5526' and p.id is null;
```

---

## 対応（本番反映済み）

### 1. `vital-add-today-fix-v1`（本番 `a8b5945`）
`weekdays` に今日の曜日が既にあると、サーバーが `ampm_per_day` を更新せず success を返していた詰み状態を修正。
モーダルの「本日表示中」判定を一覧と同じ基準（`ampm_per_day`）にそろえ、`'NONE'` が上書きされないJSのバグも修正。
→ 実在する不具合だが、**今回の主因ではなかった**。

### 2. `vital-add-id-fix-v1`（本番 `64521a0`）
追加モーダルが送る UUID を氏名経由で `patients.id` に解決するようにした。
→ これも実在する不具合だが、**主因ではなかった**。

### 3. `vital-daily-include-v1`（本番 `83f6aef`）★これが本命
**「本日の利用者を追加」を曜日の恒久設定ではなく【その日だけ】の記録に変更。あわせて 午前/午後/終日 の3択を追加。**

- 新テーブル **`vital_daily_includes`**（DDL: `db/vital_daily_includes.sql`）。**DEV・本番とも作成済み**。
- `patient_id` は**画面と同じUUID**で持つ（`vital_daily_excludes` と同じ）。ID不一致が構造的に起きない。
- 判定は1か所に集約（`templates/vitals.html` の `todayStateOf()`）:
  ```
  今日だけ削除 > 今日だけ追加(AM/PM/ALL) > 曜日の設定(第N週含む)
  ```
  **その日だけの指定が最優先**なので、第N週指定も確実に上書きできる。
- 追加処理は `patient_visit_days` を**一切触らない** → 臨時追加が翌週以降に持ち越されない。
- 新規「臨時」利用者は `patient_profiles` に作る（旧実装は `patients` にしか作らず、リロードで消えていた）。
- 日付切替時は `/api/vital_includes?date=` で取り直す。

### DEVでの実地検証（2026-08-18・全項目合格）
| 項目 | 結果 |
|---|---|
| 3択UIが出る（既定=終日） | OK |
| 追加すると一覧に出る | OK |
| **リロードしても残る** | OK |
| 午前指定が効く（午後タブで非表示） | OK |
| 翌週に持ち越さない（翌火曜の件数0） | OK |

---

## 今日のその他の作業

### 音声入力のハルシネーション対策（本番反映済み）
- 発端: ケース記録に「午後の活動では…」という創作が出た。
- 原因: `/api/transcribe` のプロンプトが「介護記録として書け」とAIに**執筆の役割**を与えていた。
- 対応（`halluc-guard-v2` / `v3` / `asr-homophone-v1`）:
  - 音声8APIすべてに `temperature 0.1`、短い録音の遮断、`[NO_SPEECH]` 方式。
  - **`utils.py` の `FastGeminiModel` は空応答を例外にして全モデル再試行する**ため、「無音なら空文字」は逆効果。合図トークン方式にした。
  - 精度が落ちた（入浴→ニューヨーク／介助→解除）ため、介護語彙を**「聞き取りのヒント」**として戻し、「書くべき内容ではない」と明示。同音異義語の対応表14項目＋誤変換の実例を追加。
- 利用者名の漢字変換（`asr-name-hint-v2` / `asr-name-kanji-v5`）:
  - 録音時ヒント（名簿照合つき）＋保存時の自動変換の二段構え。
  - **介護現場は下の名前で呼ぶことが多い**（「みさきさん」→「美咲さん」）。姓・名・フルネームの3通りに対応。
  - 敬称の直前の仮名だけを見る方式。`様(?!子)` `氏(?!名)` `君(?!主)` で誤認を防ぐ。

### 上部トーストのセーフエリア対応（`toast-safearea-v1`・DEVのみ）
iPhoneのカメラ（ノッチ）に「保存しました！」が隠れる問題。7箇所を `env(safe-area-inset-top)` 対応。

### 計画書・利用者情報シートの読み取り（`sheet-ocr-v1/v2`・DEVのみ）
- 利用者情報の基本情報6欄＋ICF付箋を、複数枚（最大8枚）まとめて読み取る。
- ボタンを基本情報の先頭へ移動、名称を「居宅サービス計画書・利用者情報シートをカメラで読み取り」に変更。
- ダミーシートでDEV検証済み: 基本情報5件＋ICF付箋16件を反映、空欄は創作せず。
- **`v2` の再検証が未実施**（左右・部位名・程度語の書き換えを禁止する修正を入れた直後にバイタル対応へ移った）。

---

## 残タスク

### すぐやること
1. **`sheet-ocr-v2` の再テスト**（DEVで「左片麻痺」「頸部」「手伝い」が正しく写るか）
   - ダミーシートは `dev/_dummy_sheets/` と `/mnt/user-data/outputs/` にある。
2. **DEVに溜まっている分の本番反映**（トースト修正・シート読み取り・ドキュメント）
   - 本番に未反映のDEVコミット: `ff0182c`(トースト) / `ac1fa62`+`29e22a0`(シート読み取り) / `b792292`+`f40ee1f`(docs)

### Apple Developer Program（審査中）
- 登録ID **`WAVNW2S5G6`** / D-U-N-S **692505882** / 法人名 `LIFE PLUS, LIMITED LIABILITY COMPANY`
- 2026-08-17 申請。**2〜4週間**が目安。**2026-09-中旬**を過ぎたらサポートへ電話。
- **D-U-N-S登録の電話番号にAppleから確認の電話が来ることがある。取り逃すと止まる。**
- ★未記録: developer.apple.com にサインインしている **Apple ID**（プロファイルで確認して追記すること）

### 商用展開まわり（コードは完成済み・管理画面の設定が未）
1. Stripe Webhook の本番登録＋`STRIPE_WEBHOOK_SECRET`
2. Cloud Scheduler の `CRON_TOKEN`
3. `PLAN_ENFORCE = True` の切替判断（現在 False・`app.py` ≈2987行）
4. 商用展開前のセキュリティ点検（Stripe / Flask SECRET_KEY / Security Advisor 残項目）

### ネイティブアプリ配布
- iPhone実機インストール（無料・審査不要）: Team ID `BB7M7M88HC` / Bundle ID `jp.lifeplus.tasukaru` 設定済み
- Android内部テスト（Google Play $25 支払い済み・追加費用なし）
- `disaster.html` の「同期について」の文言が古い

---

## 教訓（次も同じ失敗をしないために）
1. **診断SQLの結果が「0件」でも、条件が正しいかを先に疑う。** 特に facility_code。
2. **コードだけで原因を断定しない。** 今回は実データを見るまで3回外した。早い段階で実データを取りに行くべきだった。
3. 「表示されない」系の不具合は、**書き込み先**と**読み取り元**が一致しているかを最初に確認する。
4. 表示直前の上書き処理（`nth_per_day` のような）は、DBをいくら直しても勝てない。**判定の優先順位を1か所に集約する**設計にする。
