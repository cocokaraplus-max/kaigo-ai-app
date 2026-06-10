# TASUKARU 開発 引き継ぎ README

最終更新: 2026-06-10 / 対象: 接骨院会計・クレカ明細フェーズ3 一連の作業

---

## 0. このファイルの目的

次のチャット（次のセッション）で、この作業が滞りなく続けられるようにするための引き継ぎ書。
開発ルール・今どこまで終わっているか・残タスク・本番運用の注意を、ここを読めば把握できるようにまとめた。

---

## 1. プロジェクト基本情報

- アプリ: TASUKARU（タスカル）= 介護施設管理SaaS
- 構成: Flask + Supabase + Google Cloud Run（region: asia-northeast1）
- リポジトリ: `cocokaraplus-max/kaigo-ai-app`
- ブランチ: `tasukaru-dev`（DEV）／ `tasukaru`（本番）
- 運営: 合同会社LIFE PLUS
- DEV施設: `DEMO001`
  - DEV URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app/ledger
- 本番施設: `cocokaraplus-5526`（もみの木接骨院＋介護施設。実運用中）
- ログインは `staffs` テーブル（sha256）。`facilities.admin_password` ではない。

---

## 2. 開発ルール（厳守。次のセッションもこの流儀で）

### コードの受け渡し
- **コードを直接チャットに貼らない**（改行が潰れる事故防止）。
- 変更は必ず「冪等パッチ .py」方式。サンドボックスで `create_file` → 検証 → `present_files` でダウンロードリンクを渡す。
- bash の `cat << EOF` も使わない（同じ理由）。

### パッチの作法
- app.py 全体ではなく、差分を当てる小さいパッチ .py を渡す。
- 冪等性: `marker`（例 `ledger-xxx-v1`）で二重適用防止、`.bak_*` バックアップ、`assert count==1` でアンカー一意確認。
- アンカーは **実ファイルに厳密一致**させる。日本語コメントは生のUTF-8で保存されているので、`view` で正確なテキストを取得してからアンカーに使う（`\uXXXX` エスケープのまま書くと一致しないことがある）。
- grep の `<div` は `i<divisions` 等を誤検知 → `re.findall(r'<div[\s>]')` と `</div>` で厳密に数える。
- 検証手順: `python3 -m py_compile app.py` ／ ledger.html は div均衡チェック＋`node --check`（Jinjaの `{{ }}` を `null`、`{% %}` を空に置換してから）。

### HIRO（ユーザー）の作業フロー
- ローカル VSCode のターミナルで全コマンド実行、結果をチャットに貼る。
- ファイルのダウンロード: `cp ~/dev/kaigo-ai-app/app.py ~/Downloads/app.py`（templatesは `templates/ledger.html`）→ チャットに添付。
- パッチ適用: `cp ~/Downloads/パッチ.py ~/dev/kaigo-ai-app/` → `python3 パッチ.py`。
- 反映: `git add` → `git commit` → `git push origin tasukaru-dev`。
- Chrome MCP で DEV 実機確認（Browser 1, deviceId 614bb685-0ce8-4ed6-99ad-67116cf1494d）。

### 本番反映ルール
- **DDL先行**: コードのマージより前に、本番 Supabase にスキーマ（テーブル・列）を適用する。
- マージは `tasukaru-dev` → `tasukaru` の一方向。作業後は必ず `git checkout tasukaru-dev` に戻る。
- 秘密情報は端末出力・スクショに出さない。Cloud Run の secret 更新は Console UI のみ。

---

## 3. 接骨院会計・クレカ明細 全体設計

### 機能フラグ（二段構え）
- `sekkotsu_mode_allowed` + `sekkotsu_mode_enabled`（接骨院モード）
- `credit_mode_enabled`（クレカ明細モード。接骨院モードの中に入れ子）
- `divisions_enabled`（事業区分。事業ごとの会計）

### 勘定科目コード体系
- 資産=1xx（現金101, 普通預金102, 売掛金103, 未収入金104）
- 負債=2xx（買掛金201, 未払金202）
- 純資産=3xx
- 収益=4xx（介護報酬売上401, 自費売上402, 雑収入403, 接骨院自費売上404 など）
- 費用=5xx（給与501 … 雑費509, 福利厚生費510, 旅費交通費511, 接待交際費512, 材料費513, 消耗品費506 など）

### クレカ明細（内部名 orico / 画面名「クレカ明細」）
- 内部実装はオリコ前提（テーブル `ledger_orico_statements` / `ledger_orico_cards`）だが、**画面表示名は「クレカ明細」**（他社カードの施設も使うため）。
- オリコCSV: Shift-JIS(cp932)、先頭に契約情報ブロック、`<利用明細>` マーカー後に14列、金額は `"\5,880"` 形式、日付は和暦混じり、下4桁は契約番号末尾。
- 学習辞書は2つ:
  - `ledger_credit_rules`（店名/商品名 → 勘定科目）
  - `ledger_division_rules`（店名/商品名 → 事業区分。科目とは独立）
  - 推定順: 商品名(item)完全一致 → 店名(store)完全一致 → 店名部分一致(partial)。正規化は NFKC＋空白圧縮（`_cr_norm`）。
- **クレカ明細とレシートOCRは学習辞書を共用**（同じ店なら同じ科目になる）。

### 経費クレカ帳＝補助元帳（重要な概念）
- 独立テーブルではない。`journal_entries` のうち **貸方/借方が「未払金」** の仕訳を抽出した補助元帳（フロント `SUB_LEDGER_CONFIG.card`, matchFn=未払金）。
- 現金払い→貸方=現金（現金出納帳に出る）／クレカ払い→貸方=未払金（経費クレカ帳に出る）。
- 発生主義: 「買った時」借方=費用/貸方=未払金、「引き落とし時」借方=未払金/貸方=普通預金 の2段階。未払金を介してずれない。
- 税理士提出は「未払金」のまま（科目名は変えない）。画面ではバッジ等で「クレカ」と分かるようにする方針。

---

## 4. 今セッションで完了したこと（すべて DEV→本番 反映済み）

DEV最新コミット: `66faf78`（tasukaru-dev）。本番にもマージ済み（tasukaru `c818a77`）。

| 機能 | marker | 内容 |
|---|---|---|
| ステップ3a | `ledger-credit-3a-v1` | クレカ明細の各行に科目プルダウン＋登録。`credit_suggest`/`credit_assign`、費用科目のみ、学習 |
| ステップ3b | `ledger-credit-3b-div-v1` | 事業区分セレクト追加。事業の学習辞書 `ledger_division_rules` 新設 |
| ステップ3b' | `ledger-credit-3bp-v1` | キーワード部分一致ルール管理UI＋一括仮割当レビュー（`partial_rules`/`credit_preview`） |
| ステップ3b'' | `ledger-credit-3bpp-v1` | 「割当済みも見直す(上書き)」モード＋差分表示（current_account/division, is_change） |
| 見直しプレビュー修正 | `ledger-credit-3bpp-layout-v1` | プレビュー行を2段組みに（店名の縦潰れ解消） |
| ステップ4 | `ledger-receipt-learn-v1` | 領収書OCRに学習辞書を適用。`receipt_suggest`/`receipt_learn`。`entry_save`は未変更（手動仕訳に影響なし） |
| ステップ4b | `ledger-receipt-pay-v1` | OCRで支払方法判定→貸方出し分け（クレカ→未払金202 / それ以外→現金101）。OCR結果カードに支払方法バッジ（クレジット青/電子マネー紫/現金緑/不明灰） |
| OCR保存バグ修正 | `ledger-entry-id-fix-v1` | OCR仕訳が「編集」扱いになり保存されなかったバグ修正。`openEntryModal` を `entry.id` の有無で新規/編集判定に変更 |
| 科目コード自動採番 | `ledger-acct-autocode-v1` | 科目追加でカテゴリ選択時、その帯の空き番号を自動セット。`GET /api/ledger/account_next_code` |
| 経費クレカ帳の削除 | `ledger-cardledger-del-v1` | 経費クレカ帳の各行に削除ボタン＋「この月をまとめて削除」。物理削除（既存 `entry/<id>` DELETE） |
| ステップ5 税理士向け出力 | `ledger-export-journal-v1` | 仕訳帳タブに折りたたみ「税理士向け出力」。仕訳全体を期間指定でCSV/Excel。複式簿記の標準列。事業フィルタ連動。SheetJS方式（サーバ不要） |
| 補助元帳PDF | `ledger-subledger-pdf-v1` + `-fix-v1` | 現金/預金/経費クレカ/売上台帳を**サーバでPDF生成**してダウンロード。別ウィンドウ印刷を廃止し「戻れなくなる」問題を解消。`GET /api/ledger/subledger_pdf`。pdfkit(wkhtmltopdf)使用。`_esc` ヘルパー追加 |

### 本番反映の実施記録
- 本番Supabaseに `prod_ddl_credit_phase.sql`（べき等DDL）適用済み。
  - 既存だったもの: `accounts`, `ledger_divisions`, `ledger_settings`(+sekkotsu/credit列), `ledger_credit_rules`, `ledger_orico_statements`(+account_id/division_id列)
  - **このDDLで新規作成されたもの: `ledger_division_rules`, `ledger_orico_cards`**
- コードを `tasukaru-dev` → `tasukaru` にマージ（コンフリクトなし、ort strategy）→ `git push origin tasukaru`（`f19a9ca..c818a77`）→ 本番デプロイ。
- 本番では各機能フラグがオフなら新機能は非表示＝既存業務に影響しない想定。

---

## 5. 主要API早見表（接骨院会計まわり）

- `GET /api/ledger/entries?month=YYYY-MM[&division_id=N]` 仕訳一覧（debit/credit を code,name,category付きで返す）
- `POST /api/ledger/entry` 仕訳登録・更新（`entry_save`。idがあれば更新、なければ新規）
- `DELETE /api/ledger/entry/<id>` 仕訳削除（物理）
- `GET /api/ledger/accounts` 科目一覧 / `POST /api/ledger/account` 科目保存
- `GET /api/ledger/account_next_code?category=費用` 次の空き科目コード
- `POST /api/ledger/credit_suggest` / `credit_assign` クレカ明細の科目・事業 推定/保存＋学習
- `GET/POST/DELETE /api/ledger/partial_rule(s)` 部分一致ルール管理
- `POST /api/ledger/credit_preview` 一括仮割当プレビュー（only_unassigned で全件/未割当切替）
- `POST /api/ledger/receipt_suggest` レシートOCRの vendor/description＋payment_method → 借方科目・事業・貸方候補
- `POST /api/ledger/receipt_learn` レシート保存後の学習（費用科目のみ学習する安全弁）
- `POST /api/ledger/ocr_receipt` 領収書OCR（payment_method 抽出対応済み）
- `GET /api/ledger/subledger_pdf?type=cash|bank|card|sales&month=YYYY-MM[&division_id=N]` 補助元帳PDF

---

## 6. 残っているタスク

### A. 本番運用で次にやること（優先度: 高くはないが実務上いずれ必要）
1. **本番でクレカ明細・接骨院会計を使い始めるとき**:
   - 設定で `sekkotsu_mode_enabled` / `credit_mode_enabled` をオンにする。
   - 事業区分を使うなら本番 `ledger_divisions` に事業を登録し `divisions_enabled` をオン。
2. **カード引き落とし仕訳（未払金→普通預金）の記録・消し込みの仕組み**:
   - レシート/明細で「買った時」（借方費用/貸方未払金）を積むと未払金が増え続ける。
   - 引き落とし日に「未払金/普通預金」を計上しないと未払金が残りっぱなしになる。
   - 自動化（クレカ明細CSVの引き落とし額をまとめて計上 等）は未実装。運用が固まったら設計する。

### B. 将来タスク（優先度: 低。メモリにも記録済み）
1. **レシート×明細の突合（段階2・3）**:
   - 段階2: レシート×クレカ明細(`ledger_orico_statements`)を金額・日付近接・店名で照合→一致でクレカ払い確定→貸方=未払金。Amazon突合ロジックの応用。
   - 段階3: レシート×電子マネー明細の突合。**前提注意**: 既存のキャッシュレス振替（`ledger-cashless-v1`, `cashless_match`/`apply`, `_cashless_parse` PayPay/楽天）は CSV をその場で `journal_entries` に update するだけで**電子マネー明細を保存していない**。段階3には電マネ明細テーブルの新設が別途必要。
   - HIROの事業は電子マネー未使用のため優先度低。他施設向けに将来搭載。電マネ用勘定科目は未確認。
2. **OCRの実レシートでの支払方法判定の精度検証**:
   - 実物レシートで payment_method（credit/cash/emoney/unknown）が正しく読めるか検証。
   - 精度OKなら経費クレカ帳タブの説明文（marker `tab-desc-v1`/`v2`）に「OCRから読み取って入れることもできる」を追記。

### C. DEVのテストデータ掃除（Claudeが検証中に作成）
- 経費クレカ帳(2026-06)の仕訳: 「テスト」「スギ薬局テスト」「マツモトキヨシ検証」「クレカ判定検証店」など（貸方=未払金）。
- 学習辞書のテストデータ: 「テスト薬局ZZ」「マツモトキヨシ検証」「ENEOS-SS」など。
- ETC明細36件に入れたテスト科目・事業（DEMO001）。
- → 経費クレカ帳の削除ボタンで消せる。**本物のレシート行は残すこと**。DEVのみなので実害なし。

---

## 7. 本番反映の手順テンプレ（次に別機能を本番へ出すとき）

1. DEVで実装・push・実機確認まで完了させる。
2. 新しいテーブル・列があれば、**べき等DDL**（`IF NOT EXISTS`＋制約は存在チェック）を作り、本番Supabaseの現状を `information_schema` で確認してから本番SQL Editorで適用。
   - 本番プロジェクトであることを必ず確認（DEVと取り違えない）。
3. `git checkout tasukaru` → `git merge tasukaru-dev` → コンフリクトが無いことを確認 → `git push origin tasukaru`。
4. `git checkout tasukaru-dev` に戻る。
5. 本番デプロイ後、既存機能が壊れていないか確認。新機能はフラグをオンにして確認。

---

## 8. 既知の注意点・ハマりどころ

- `ledger.html` のJS文字列内の日本語を新規に書くときは `\uXXXX` で（`node -e` で展開確認できる）。ただし**既存コードのアンカー**は生の日本語UTF-8なので、`view` で実テキストを取ってからアンカーにする。
- `entry_save`（仕訳保存）は手動/OCR/編集で共用。学習などの副作用を足すときは `entry_save` 本体を触らず、別エンドポイントに分離してフロントから保存成功後に呼ぶ（ステップ4の設計がその例）。
- PDF生成は WeasyPrint ではなく **pdfkit(wkhtmltopdf)**。`shutil.which('wkhtmltopdf')` でパス解決。関数内で `import shutil` を忘れない（500エラーの原因になった）。
- div均衡・JS構文チェックは毎回やる。とくにテンプレHTML文字列を足すと開閉がずれやすい。
