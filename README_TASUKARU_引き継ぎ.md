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
2. **OCRの実レシートでの支払方法判定の精度検証**【完了 / readme-redesign-v1】:
   - 実物レシートで payment_method（credit/cash/emoney/unknown）が正しく読めるか検証。
   - 精度OKなら経費クレカ帳タブの説明文（marker `tab-desc-v1`/`v2`）に「OCRから読み取って入れることもできる」を追記。

### C. DEVのテストデータ掃除【完了 / readme-redesign-v1】
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

---

## 9. 会計モジュール再設計の方針（このセッションで決定）<!-- readme-redesign-v1 -->

> このセクションは設計の合意事項。**実装はまだ。次セッション以降で着手する。**
> 経緯: クレカの記録経路が「クレカ明細CSV」「経費クレカ帳の手入力」「OCR」の3つに散り、
> どこに入れるか迷う/二重計上の懸念があった。これを整理した結論が以下。

### 9-1. 確定した設計（実装対象）

1. **仕訳帳を入力ハブに一本化**。収入も支出も全部そこで入力。各帳簿（現金出納帳/預金出納帳/クレカ未払/売上台帳）は仕訳を絞り込んで見る**閲覧ビュー**に徹する。
2. **経費クレカ帳タブは廃止**し、仕訳帳に統合（クレカ＝貸方未払金の閲覧は補助元帳ビューとして残す）。
3. **クレカ明細CSV・領収書OCRを全施設に開放**。＝**クレカ機能の接骨院モード依存を外す**（現状 `sekkotsu_mode_enabled` > `credit_mode_enabled` でガードされているのを解除）。
4. **初回モーダルで記録方法を選ばせる**（出納帳の初回利用時、未選択なら表示・スキップ不可）。
   - 文言確定: 見出し「クレジットカードの利用履歴の記録方法は？」、補足「あとから設定で変えられます」。
   - 選択肢: 「**使用したレシートから記録する**」（=OCR方式） / 「**CSVを読み込んで記録する**」（=CSV方式）。
   - 選択値は `ledger_settings` に1列で保持（例: `credit_input_method` = 未選択/ocr/csv。命名は実装時）。未選択ならモーダルを出す。
5. **選択で施設が2タイプに分岐**（排他）:
   - **CSV方式**: クレカはCSV取込。OCRは**現金専用**（クレカと判定されても仕訳化しない＝レシート保管庫に残すだけ）。CSV取込画面が出る。
   - **OCR方式**: クレカは仕訳帳の手入力 or OCRで仕訳化。**CSV取込画面は出さない**。
6. **排他により二重計上が構造的に発生しない**（CSV方式はOCRからクレカを入れられない／OCR方式はCSV画面が無い）。
7. **レシート保管庫ビューを新設**（`receipts` 一覧。`receipts.entry_id`（既存・bigint）で「仕訳済み/未仕訳」を判別。**新テーブル不要**。読み出しAPIとUIを足すだけ）。

### 9-2. 実装しないと決定したもの

- **常時のレシート×クレカ明細CSV突合（旧 6-B-1 段階2）は実装しない**。理由: HIROの運用ではクレカはCSVが正で完結し、突合の動機がない。クレカOCRレシートは「後で本当にクレカか確認する」材料として保管庫に残すだけ。
- 旧 6-B-1 段階3（電子マネー明細突合）も当面対象外（HIRO事業は電マネ未使用）。

### 9-3. 将来実装・設計中（今は作らない）

- **記録方法の「後からの変更」機能**。実質「**OCR方式 → CSV方式**」の一方向移行のみ想定（手間の多いOCRから楽なCSVへ移る動機はあるが、逆は起きにくい）。初回選択を持つ設定さえ用意しておけば、変更UIは後から無理なく足せる作りにする。
- **乗り換え時の二重計上チェック（重要な設計知見）**: 店頭でのクレカ決済は**レシート日付＝カード利用日が一致**し、**1レシート＝1決済**（Amazonのように注文日/課金日のズレや分割決済が無い）。そのため OCR で既入力のクレカ仕訳と CSV 行を「**日付完全一致＋金額完全一致**」という強い条件で突合でき、偶然一致がほぼ無く自動判定の信頼度が高い。乗り換え機能を作るときは、この硬い突合で既入力分を検出し CSV 側からスキップ/警告すればよい。これは常時突合（9-2で不要とした旧段階2）とは別物で、**乗り換え時だけ動く軽い仕組み**でよい。
- **接骨院モード依存を外す具体的なコード箇所の洗い出し**は次セッション（`credit_mode_enabled` / `is_credit_enabled` / サーバガード `ledger-credit-guard-v1` 5箇所 / フロントの表示条件など）。

### 9-4. 実装後にやる

- **アプリ内ガイドにこの記録方法選択モーダルの説明を掲載**（レシート派/CSV派の違い、後から変更できること）。**実装が動いてから**載せる（ガイドは"今ある姿"を書くもの。先行させると実態とズレる）。
- 旧6-B-2の「経費クレカ帳タブ説明文に『OCRから読み取れる』を追記」は、経費クレカ帳廃止に伴い**不要化**（説明先のタブ自体が無くなる）。

### 9-5. このセッションで完了した作業

- **C. DEVテストデータ掃除: 完了**。経費クレカ帳テスト仕訳3件削除 / クレカ明細(orico)のテスト割当56件クリア（行は実データとして保持）/ 学習辞書24件全削除。すべて DEMO001 のみ。
  - **教訓**: Supabase SQL Editor は **BEGIN; ... COMMIT; を別実行に分けると確定しない**（オートコミット前提でトランザクションが切れる）。確認SELECTと変更文(DELETE/UPDATE)は分け、**変更文は単発で実行**して、後からSELECTで件数を確かめる流儀にする。
- **B-2. OCR支払方法判定の精度検証: 合格**。実レシートで確認した傾向 ＝ 支払方法が分かる形（印字・手書きの現金欄レ点チェック含む）なら確実に正答 / 印字が無ければ安全に unknown（推測で誤爆しない）/ ポイントカード会員番号には釣られない。実運用に十分な精度。

---

## 10. 再設計の実装進捗（このセッション）<!-- readme-impl-progress-v1 -->

セクション9の設計に基づく実装を開始。バックエンド土台＋初回モーダルまで DEV で完了・検証済み。

### 10-1. DEVに反映・検証済みの実装

| 段階 | marker | ファイル | 内容 | 検証 |
|---|---|---|---|---|
| 第一歩 | `ledger-credit-method-v1` | app.py | `is_credit_enabled` を接骨院モード非依存化（`credit_input_method` が null以外でTrue）。設定 get/save に `credit_input_method` 対応 | DEMO001='csv'でクレカ機能が従来通り動作 |
| 第二歩-b | `ledger-credit-csvguard-v1` | app.py | `is_credit_csv_enabled`（`credit_input_method=='csv'`）を新設。CSV方式専用ガード13箇所を差し替え | receipt方式でCSV専用API=403、csv方式=200 の開閉を実証 |
| 第二歩-a | `ledger-credit-method-modal-v1` | templates/ledger.html | 出納帳初回に「記録方法は？」モーダル（レシート/CSV）。`loadSettings`末尾で未選択なら表示、`chooseCreditMethod()`で保存→再ロード | モーダル表示→選択→方式別にAPI開閉を実機確認 |

- **DDL（DEV適用済み）**: `ledger_settings.credit_input_method` text（null / 'receipt' / 'csv'、CHECK制約 `ledger_settings_credit_input_method_chk`）。既存 `credit_mode_enabled=true` 施設（DEMO001）を 'csv' に移行。
- **DEV現状**: DEMO001 = csv 方式。

### 10-2. 重要な前提（このセッションで確認）

- **出納帳機能はデフォルトOFFの許可制**。現状は「開発者MENU内のトグル」でHIROが手動許可した人だけが使える（`admin_settings` の `ledger_users`/`ledger_enabled`、未許可は `/top` へリダイレクト）。
  - → 初回モーダルは「出納帳を開けた＝許可済み施設」にだけ出るので、無関係な施設に出る心配はない。本番反映しても安全。

### 10-3. 本番反映の手順（このセッションで実施予定）

1. 本番Supabaseに DDL（`credit_input_method` 列＋CHECK制約）を適用。※本番にcredit_mode施設が無ければ移行UPDATEは0件。
2. `tasukaru-dev` → `tasukaru` をマージ（app.py 2パッチ＋ledger.html 1パッチ）→ push → 本番デプロイ。
3. 本番（cocokaraplus-5526、出納帳許可済み）で出納帳を開く → 初回モーダルが出る → CSV方式を選択（HIROはオリコCSV利用のため）。
4. `git checkout tasukaru-dev` に戻る。

### 10-4. 残実装（次セッション）

- **キーワード振り分けルールの品名対応**（readme-followups-v1 で記録）: 現状の部分一致ルール `partial_rule` は `key_type='store'` 固定で店名（`used_for`）にのみ部分一致。品名（例:「ウェットティッシュ」）でもキーワード指定できるよう `key_type='item'` の部分一致に対応したい（HIRO要望）。要設計: 店名と品名の優先順位 / オリコ明細では品名がAmazonの `amazon_detail` にしか無い点 / 既存のitem完全一致ロジックとの整合。部分一致UIは `ledger.html` の `partial_rules` 管理画面、APIは `partial_rule` POST/DELETE。

- **2-c: 経費クレカ帳タブの廃止＆仕訳帳統合**（最大の改修。仕訳帳を入力ハブに、各帳簿は閲覧ビュー化）。
- **レシート保管庫ビュー新設**（`receipts` 一覧。`receipts.entry_id` で仕訳済み/未仕訳を判別。新テーブル不要）。
- フロントの旧トグル（接骨院モード内のクレカ明細トグル `credit-mode-card` / `credit_mode_enabled`）の整理。新方式（credit_input_method）に一本化するなら旧トグルは撤去候補。

### 10-5. 将来課題（優先度低・他施設向け）

- **大手ECの注文履歴CSV突合**（楽天・Yahoo!ショッピング等）。現状の突合はAmazon専用（`_amazon_match_against_orico`）。各社CSV形式ごとにパーサ追加が必要。実店舗は突合相手のCSVが存在しないため対象外。
- **出納帳の一般リリース時のアクセス制御**。現状の「開発者MENU手動トグル許可」はクローズドベータ向け。一般公開時はプラン連動や施設セルフ有効化など別の仕組みを設計する必要がある。

### 10-6. 本番反映実績と旧記載の訂正<!-- readme-followups-v1 -->

- **本番反映完了（このセッション）**: DDL（credit_input_method列）を本番Supabaseに適用、app.py 2パッチ＋ledger.html 1パッチを `tasukaru-dev`→`tasukaru` マージ（コンフリクト無し、ort）→ push（c818a77..328e222）→ 本番デプロイ。本番 cocokaraplus-5526 で動作確認済（モーダル出ない・クレカ明細表示・科目割当動作）。
- **旧記載の訂正（重要）**: メモリ・旧READMEの「本番にはクレカ明細機能を一切出していない=DEVのみ」は**誤り**だった。実際には本番 cocokaraplus-5526 で `credit_mode_enabled=true`、オリコ明細 **222件** を取込済みで実運用していた。そのため本番DDLでも移行UPDATE（credit_input_method='csv'）が1件発生し、これが無いと新コードで本番のクレカ機能が見えなくなるところだった。今後「本番は未使用」と思い込まないこと。

---

## 11. このセッションの最終状態と次回への引き継ぎ<!-- readme-session-close-v1 -->

### 11-1. このセッションで本番まで反映し終えたもの

1. **会計モジュール再設計（土台＋初回モーダル）** — DEV→本番 反映済み。
   - `ledger-credit-method-v1`（is_credit_enabled を接骨院モード非依存に。credit_input_method で判定）
   - `ledger-credit-csvguard-v1`（is_credit_csv_enabled 新設。CSV方式専用ガード13箇所を差し替え）
   - `ledger-credit-method-modal-v1`（出納帳初回の「記録方法は？」モーダル。receipt/csv 排他選択）
   - DDL `ledger_settings.credit_input_method`（null/receipt/csv, CHECK制約）を **DEV・本番の両Supabaseに適用済み**。
   - 本番コミット: `c818a77..328e222`。
2. **キーワード振り分けルールの品名対応** — DEV→本番 反映済み。
   - `ledger-credit-itempartial-v1`（app.py: item部分一致をマッチ/保存/取得/削除に対応）
   - `ledger-credit-itempartial-front-v1`（ledger.html: 店名/品名セレクト・バッジ・key_type送信）
   - マッチ優先順位: 品名完全→店名完全→**品名部分→店名部分**。DDL不要（既存のkey_type列を使用）。
   - 本番コミット: `328e222..bc6e6c4`。
   - 本番(cocokaraplus-5526)で動作確認済み: 店名/品名セレクト表示・事業セレクト表示・既存ルール温存・クレカ明細222件健在。

### 11-2. DEVの現状メモ

- DEMO001 の `credit_input_method` = **'csv'**。
- DEMO001 の `divisions_enabled` を**このセッション中に false→true に変更**した（キーワードルールの事業セレクト確認のため）。テスト施設なので実害なし。気になれば設定でoffに戻してよい。
- DEVの学習辞書・クレカ明細のテスト割当はクリーン（このセッション最初に掃除済み）。クレカ明細の実データ132件は保持。

### 11-3. 既知の小さな挙動（次回直すか判断）

- **クレカ明細タブを switchTab('orico') で開いただけでは initKwrule() が呼ばれない**。キーワード振り分けルールのアコーディオンを開いたとき（toggleKwrule の `if(open) initKwrule()`）に初めて事業・科目セレクタが初期化される。実用上はアコーディオンを開けば出るので動くが、「設定で事業区分をONにしてもタブを開いた直後はセレクトが空」に見える。気になるなら switchTab('orico') 時に initKwrule() も呼ぶ小修正を入れる（ledger.html 737行 switchTab / 753行 loadOrico 付近）。

### 11-4. 残タスク（次セッション、優先度順）

1. **2-c: 経費クレカ帳タブの廃止＆仕訳帳統合**（再設計の本丸・最大の改修）。
   - 仕訳帳を入力ハブに、各帳簿（現金/預金/クレカ未払/売上）は閲覧ビューに徹する。
   - 経費クレカ帳タブ(`pane-card` / `tab-card`)を撤去し、未払金の閲覧は補助元帳ビューとして残す。
   - 影響範囲が広いので、現状の各帳簿の入力/表示ロジックを読んでから着手すること。
2. **レシート保管庫ビュー新設**（receipts一覧。`receipts.entry_id`(bigint, 既存)で仕訳済み/未仕訳を判別。新テーブル不要。読み出しAPI＋UIを足すだけ）。
3. **フロントの旧トグル整理**: 接骨院モード内のクレカ明細トグル(`credit-mode-card` / `credit_mode_enabled`)は、新方式(credit_input_method)に一本化するなら撤去候補。再設計が進んだら整理する。
4. **11-3の小修正**（switchTab('orico')でinitKwrule呼ぶ）を入れるか判断。

### 11-5. 将来課題（優先度低）

- 大手EC（楽天/Yahoo!ショッピング等）の注文履歴CSV突合。現状はAmazon専用(`_amazon_match_against_orico`)。各社CSV形式ごとにパーサ追加が必要。実店舗は突合相手CSVが無く対象外。
- 出納帳の一般リリース時のアクセス制御。現状は開発者MENU手動トグル許可(`admin_settings.ledger_users`/`ledger_enabled`)のクローズドベータ。一般公開時はプラン連動等を設計。
- レシート×クレカ明細の突合（乗り換え時）。店頭クレカはレシート日付=利用日が一致・1レシート=1決済なので「日付完全一致＋金額完全一致」で硬く突合できる（Amazon突合と違い曖昧さがない）。乗り換え時だけ動く軽い仕組みでよい。常時突合(旧B-1段階2)は実装しないと決定済み。

### 11-6. 次回の開始手順とファイル受け渡し

- **ブランチ**: 開発は `tasukaru-dev`、本番は `tasukaru`。本番反映は DDL先行 → マージ → push → `tasukaru-dev` に戻る。
- **ファイル受け渡し（このセッションと同じ方式）**: Claudeが必要なファイルのダウンロードコマンド（例: `cp ~/dev/kaigo-ai-app/app.py ~/Downloads/app.py` / templatesは `cp ~/dev/kaigo-ai-app/templates/ledger.html ~/Downloads/ledger.html`）を出す → HIROが実行し、出てきたファイルをチャットに添付する。最新の app.py / ledger.html が必要なときは遠慮なく依頼する。
- **コード変更**: 直貼り禁止。冪等パッチ.py（marker＋.bak＋assert count==1）をサンドボックスで作成→検証→present_filesでダウンロードリンク。bashの `cat << EOF` も禁止。
- **検証**: app.py は `python3 -m py_compile app.py`。ledger.html は div均衡（`re.findall(r'<div[\s>]')` と `</div>`）＋ Jinja置換後の `node --check`。
- **SQL運用の教訓**: Supabase SQL Editor は BEGIN/COMMIT を別実行に分けると確定しない（オートコミットで切れる）。変更文(DELETE/UPDATE)は単発で実行し、後からSELECTで件数確認する。

---

## 12. 2-c 経費クレカ帳タブ廃止＆仕訳帳統合 — 本番反映完了<!-- readme-2c-done-v1 -->

セクション11-4の残タスク①（再設計の本丸）を実装し、DEV→本番まで反映完了。

### 12-1. 本番まで反映し終えたもの

1. **経費クレカ帳タブの廃止＆未払金の補助元帳ビュー化** — DEV→本番 反映済み。
   - `ledger-2c-cardtab-retire-v1`（templates/ledger.html）:
     - ナビの「経費クレカ帳」タブボタン(`tab-card`)を撤去。
     - 仕訳帳タブ内（税理士向け出力パネルの直下）に「💳 未払金（クレジットカード等）」補助元帳リンクを新設→`switchTab('card')`で開く。
     - `pane-card` 先頭に「‹ 仕訳帳に戻る」リンクを新設（タブが無くなったための戻り導線）。
     - カード帳の削除UI（行ごとの削除ボタン・「この月をまとめて削除」・操作列ヘッダ/フッタ・関数 `deleteCardEntry`/`deleteCardMonth`）を撤去し**閲覧専用化**。
   - `ledger-2c-cardview-heading-v1`（templates/ledger.html）:
     - 見出し「経費クレカ帳（未払金）」→「未払金（クレジットカード等）」。
     - 説明文「領収書のクレジットカード利用を記録します。」→「クレジットカード等による未払金の補助元帳です。入力は仕訳帳から行います。」。
     - `SUB_LEDGER_CONFIG.card.label`「経費クレカ帳（未払金）」→「未払金（クレジットカード等）」（Excel/PDF出力のタイトル・ファイル名・シート名に反映）。
   - **DDL不要・app.py変更なし**（ledger.html のみの改修）。
   - コミット: DEV `a65354b`（タブ廃止）→ `3e54219`（見出し修正）。本番マージ `57d8a0a`（bc6e6c4..57d8a0a）。
   - ※本番マージには前回未反映だった README更新 `af8b0e4`（readme-session-close-v1）も同梱された（ドキュメントのみ・実害なし）。

### 12-2. 設計判断・確認した事実（このセッション）

- **未払金ビューは元々ほぼ閲覧ビューだった**。`pane-card` は cash/bank/sales と同じ `loadSubLedger('card')`＋`SUB_LEDGER_CONFIG.card.matchFn`（借方/貸方に未払金を含む仕訳を抽出）で描画する読み取りビューで、カード帳専用の入力フォームは無い。再設計の「仕訳帳を入力ハブに、各帳簿は閲覧ビュー」は未払金については構造的に達成済みで、2-cの実体は「タブをナビから外す＋削除UIを外す＋導線/文言を整える」だった。
- **削除UIを外しても機能欠落なし**。仕訳帳タブに個別仕訳の編集/削除ボタン（`editEntry`/`deleteEntry`、同じ `/api/ledger/entry/{id}` DELETE）があるため、未払金仕訳の削除は仕訳帳側で可能。
- **CSV取込の「カード利用履歴」選択肢(`<option value="card">`)は温存**（HIRO判断: 汎用CSVでもカード明細を入れたい）。クレカ明細(orico)タブとは別経路として残す。
- **switchTab系ロジックは温存**。`'card'` は forEach の表示制御配列・`_monthTabs`（月ナビ表示）・`if(tab==='card') loadSubLedger('card')` に残してあり、リンクから `switchTab('card')` を呼べば pane-card が開く。撤去したのはナビボタンと削除UIのみ。

### 12-3. DEVでの検証（Chrome MCP・DEMO001）

- ダミー未払金仕訳3件（借方=消耗品費/通信費/福利厚生費・貸方=未払金、2026-03）をUIの＋ボタン経由(`saveEntry`)で投入→未払金ビューに表示・列ずれ無し・削除ボタン無しを確認→「‹ 仕訳帳に戻る」動作確認→テスト3件(id 351/352/353)を `/api/ledger/entry/{id}` DELETE で掃除（実データ id 350 は温存）。
- 見出し・説明文・出力ラベルが新文言に変わったことを本番デプロイ後の再読込で確認。

### 12-4. 残タスク（次セッション、優先度順）

1. **レシート保管庫ビュー新設**（旧①が完了したので、これが次の最優先）。`receipts` 一覧。`receipts.entry_id`(bigint, 既存)で仕訳済み/未仕訳を判別。新テーブル不要。読み出しAPI＋UIを足すだけ。
2. **フロントの旧トグル整理**: 接骨院モード内のクレカ明細トグル(`credit-mode-card` / `credit_mode_enabled`)は、新方式(`credit_input_method`)に一本化するなら撤去候補。
3. **11-3の小修正**（`switchTab('orico')` で `initKwrule()` を呼ぶ）を入れるか判断。

### 12-5. 後始末の宿題（独立コミットで処理する）

- **追跡されている空ファイル `tasukaru-dev`（0バイト）がリポジトリ直下にある**。コミット `ee3a3c9`（iPhoneデバッグのalert追加）で誤って混入したもの。ブランチ名 `tasukaru-dev` と曖昧になり `git log tasukaru-dev` がファイル解釈でエラーになる（`git log refs/heads/tasukaru-dev` で回避）。実害は無いが、`git rm tasukaru-dev` → コミット（2-c等の機能変更とは混ぜず単独で）で両ブランチから消すのが望ましい。同様に `README_tasukaru_dev.md` も直下にあるが、こちらは中身のあるドキュメントなので残す。

---

## 13. ビルド障害の顛末と教訓（2026-06-11）<!-- readme-build-incident-v1 -->

2-cの本番マージ後、本番Cloud Buildが連続して失敗した。原因は**2件とも2-cのコードとは無関係**で、いずれも依存・ビルド環境側の問題だった。記録しておく。

### 13-1. 障害1: requirements.txt 全未固定による pip 依存衝突

- **症状**: 本番ビルド `57d8a0a`（と同内容）で Step 0 Build の `pip install -r requirements.txt` が `ResolutionImpossible` で失敗。
- **ログ**: `supabase 0.0.3 depends on requests==2.25.1` と `google-genai 2.x depends on requests>=2.28.1` が両立せず。
- **真因**: `requirements.txt` が `openpyxl==3.1.5` 以外**全部バージョン未固定**だった。Dockerfileが `--no-cache` でビルドするため毎回その時点のPyPI最新を解決しにいく。この日、pip(24.0)のリゾルバが衝突回避のため supabase を初期版 `0.0.3`（依存がほぼ無い壊れた版）まで巻き戻し、その `requests==2.25.1` 固定が google-genai と衝突した。コード変更ではなく**未固定依存の時限爆弾が当日のPyPI状態でたまたま発火**した。
- **対処**: `req-pin-v1`。直接依存14件を、2026-06-11時点でサンドボックスの `pip install --dry-run` が衝突なく解決する組み合わせに固定。主要: `supabase==2.31.0` / `google-genai==2.8.0`（この2.x系は requests を直接固定しないので衝突しない）。`requirements.txt` 先頭にmarkerコメントと運用ルールを記載。
- 固定後、DEVビルド（`f99a7cc`）が緑になり解消を確認。

### 13-2. 障害2: pypi.org への一時的な接続タイムアウト

- **症状**: req固定済みの本番ビルド `b534b88`（`c708090e`）が再び Step 0 で失敗。だが**同内容のDEVビルドは緑**。
- **ログ**: `WARNING: Retrying ... ReadTimeoutError(... pypi.org ... Read timed out)` を5回繰り返した後 `ERROR: Could not find a version that satisfies the requirement httpcore==1.* (from versions: none)`。`from versions: none` は候補リストすら取得できなかった＝**ネットワーク起因**を示す。
- **真因**: 依存衝突ではなく、`httpcore` 取得時に pypi.org への接続がタイムアウトしただけ。req固定は正しく効いていた（ログ前半で supabase==2.31.0 等は正常にCollect済み）。本番ビルドのタイミングでたまたまPyPI接続が悪かった。
- **対処**: コンソールの「ビルドを再試行」を押下 → 緑で完走。コード/設定の変更は不要だった。

### 13-3. 教訓（次回これで慌てない）

1. **未固定依存は時限爆弾**。`requirements.txt` は固定する。`--no-cache` ビルドは毎回最新解決＝ある日突然壊れうる。バージョンを上げるときは `pip install --dry-run -r requirements.txt` が衝突なく通ることを確認してから1つずつ。
2. **ビルドが赤でも即「依存衝突」と決めつけない**。**同じソースで DEV 緑・本番 赤**なら、依存ではなく**一時的ネットワーク**（pypi.org の Read timed out → `No matching distribution` / `from versions: none`）の可能性。まず「ビルドを再試行」で通るか試す。
3. **ログ末尾を必ず読む**。`gcloud builds log <BUILD_ID> --region=global --project=tasukaru-production | tail -50` でStep0のpip出力まで確実に読める（コンソールUIはStep0ログが「表示するログはありません」になることがある）。`ResolutionImpossible`（依存衝突）か `ReadTimeoutError`（ネットワーク）かで対処が真逆。

### 13-4. 将来の改善候補（任意）

- Dockerfile に `RUN pip install --upgrade pip` を `pip install -r requirements.txt` の前に入れると、リゾルバが新しくなり supabase が初期版へ巻き戻る類の事故を予防できる（今回は固定で回避済みなので必須ではない）。
- pip のネットワーク耐性を上げるなら `pip install --timeout 60 --retries 10 ...` を検討（httpcoreタイムアウト対策）。今回は再試行で足りたので未実施。



## 14. レシート保管庫・記録方法の排他・ガイド整備（2026-06-11 本番反映済み）<!-- readme-receipt-credit-v1 -->

このセッションで出納帳（会計モジュール）に5件を実装し、すべて DEV検証→本番（cocokaraplus-5526）反映済み。本番ブランチ `tasukaru` のマージコミットは `19a555d`。本番はCSV方式（`credit_input_method='csv'`）。**今回はDDL追加なし**（FK制約変更は §14-2 のとおり ALTER のみ、両環境適用済み）。

### 14-1. 実装した5件（コミット順）

1. **レシート保管庫ビュー＋OCR仕訳紐付け**（`fb2b48b`）
   - app.py: `ledger-receipt-link-v1`（`/api/ledger/entry` 新規作成時に `receipt_id` があれば `receipts.entry_id = new_id` を埋める）、`ledger-receipt-vault-v1`（`GET /api/ledger/receipts` 保管庫読み出しAPI。`entry_id` 有無で仕訳済み/未仕訳を判別。新テーブル不要）。
   - ledger.html: `ledger-receipt-link-front-v1`（OCR→仕訳の `receipt_id` 引き回し。`createEntryFromOCR(ocr, receiptId)` → `window._ocrReceiptId` → `saveEntry` が `payload.receipt_id` 同送）、保管庫UI＋JS（`loadReceiptVault`/`setReceiptFilter`/`renderReceiptVault`、`pane-receipt` 内・`switchTab('receipt')`で自動ロード）。
   - **重要な前提**: この紐付け実装より前のレシートは全て `entry_id=null`（未仕訳表示）。過去分が未仕訳で出るのは正常。

2. **クレカ明細タブの仕訳状態フィルタ**（`cbffb7f`、ledger.htmlのみ）
   - `ledger-orico-filter-front-v1`。判別基準は **`account_id`（勘定科目）の有無**。割当済み=仕訳済み、null=未仕訳。`loadOrico` を「取得→`window._oricoCache`→`renderOrico()`」に分離し、3ボタン（すべて/未仕訳/仕訳済み）＋件数サマリ。フィルタ後に行が残らない月グループは非表示。app.pyは `account_id` を既に返すため変更不要。

3. **① CSV方式はOCRクレカの仕訳化を弾く**（`3847f92`）
   - app.py: `ledger-credit-ocrguard-v1`（`/api/ledger/entry` で `receipt_id` あり・新規・CSV方式かつ DBの `receipts.ocr_result.payment_method=='credit'` なら **409 `credit_csv_blocked`**。改ざん耐性のためDBを引く。編集 `data['id']` は対象外）。
   - ledger.html: `ledger-credit-ocrguard-front-v1`（`createEntryFromOCR` 冒頭で CSV方式かつ `ocr.payment_method=='credit'` なら案内alert＋中断。OCR結果カード・保管庫カード両方がこの関数を通るので一括カバー）。
   - 弾く対象は **CSV方式×クレジットのみ**。現金/電子マネー/unknown、OCR方式、未選択は通す。OCRの支払方法判定は §9-5（`ledger-receipt-pay-v1`）で精度実証済みなので信頼できる。

4. **② 記録方法でクレカ明細タブ・カード選択肢を出し分け**（`9849d31`、ledger.htmlのみ）
   - `ledger-credit-method-show-v1`。**CSV方式のときだけ** クレカ明細(orico)タブ・会社カード管理セクション・CSV取込の「カード利用履歴」選択肢を表示。OCR方式・未選択では隠す。従来 `credit_mode_enabled`（旧フラグ）制御だった箇所を `credit_input_method=='csv'` に統一。
   - 領収書OCRタブ・CSV取込タブ自体は両方式で表示（日計表・キャッシュレス等の共通機能のため、タブごとは消さない）。

5. **ガイド常時表示＋OCRステップに記録方法のモック**（`f56fa7e`、ledger.htmlのみ）
   - `ledger-guide-method-v1`。作業手順マニュアル（ガイド）タブを `sekkotsu_mode_enabled` 連動から**常時表示**に変更。出納帳ページ（`/ledger`）は未許可者を `redirect('/top')` で弾く（開発者MENUのトグルでHIROのみ許可）ため、ガイドが見えるのは出納帳を許可された人だけ＝意図どおり。
   - ステップ4（経費・領収書/領収書OCR）に「クレジットカードの記録方法」見出し＋SVGモック図を追加。`renderGuideMethod(credit_input_method)` で出し分け。CSV方式＝「この施設はCSV方式です…保管庫に保管」＋分岐図（既存Amazon突合図と同テイスト・角丸ボックス＋矢印＋色分け）、receipt方式＝「レシート方式です…OCRから仕訳化」＋単純フロー図、未選択＝設定を促す案内。**施設ごとに説明文・図が自動で切替**（DEV/本番とも実機確認済み）。

### 14-2. 重要な設計知見: `receipts.entry_id` の FK制約を `ON DELETE SET NULL` に統一

- `receipts.entry_id` には FK制約 `receipts_entry_id_fkey`（`REFERENCES journal_entries(id)`）がある。
- 当初 **DEVは `ON DELETE SET NULL`、本番は `ON DELETE`句なし（NO ACTION）** とズレていた。NO ACTION のままだと、OCR紐付き仕訳を仕訳帳から削除しようとすると `23503` で失敗する（レシートが参照しているため）。
- 対処として**両環境を `ON DELETE SET NULL` に統一**（本番は §14 反映時に ALTER 実行済み）。これで仕訳を削除すると `receipts.entry_id` が自動でnullに戻り、レシートは保管庫に「未仕訳」として残る。孤児参照が出ない。DEVで実証（仕訳削除→receipt自動null戻り確認）。
- 適用したDDL（既存制約を落として張り直し）:
  ```sql
  ALTER TABLE receipts DROP CONSTRAINT receipts_entry_id_fkey;
  ALTER TABLE receipts ADD CONSTRAINT receipts_entry_id_fkey
    FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE SET NULL;
  ```
- **次に別環境（新規施設DB等）を立てるときは、この制約が `SET NULL` になっているか確認すること。**

### 14-3. 記録方法による排他の全体像（完成形）

施設ごとに `credit_settings.credit_input_method`（`receipt` / `csv` / null）で排他。二重計上を構造的に防ぐ。

- **CSV方式（csv）**: クレカは CSV（クレカ明細）が正。クレカ明細タブ・会社カード管理・「カード利用履歴」選択肢を表示。領収書OCRでクレジット判定されたレシートは**仕訳化を弾く**（フロント案内＋サーバ409）＝保管庫に残すだけ。現金/電子マネー/unknownはOCRで仕訳化OK。
- **レシート方式（receipt）**: クレカも含め全てOCR（または仕訳帳手入力）で記録。クレカ明細タブ・カード選択肢は非表示。OCRのクレカも普通に仕訳化できる。
- 設計思想: **仕訳帳が入力ハブ**。OCR/CSVはそこへの補助経路。「その施設に関係するUI・説明だけ見せて迷わせない」。

### 14-4. 既知の小課題（次回任意）

- **保管庫一覧の最終カードがボトムナビと重なる**: `pane-receipt` 内の保管庫一覧を最下部までスクロールすると、最後のカードのボタンがボトムナビ（TOP/記録入力…）の裏に入り画面操作しづらい。`pane-receipt` 末尾に下部パディングを足せば解消。
- **空ファイル `tasukaru-dev`（0バイト・リポジトリ直下）の単独 `git rm`** が依然未対応（§12-5）。機能変更と混ぜず単独コミットで消す。`git log tasukaru-dev` がファイル解釈でエラーになる回避は `git log refs/heads/tasukaru-dev`。

### 14-5. このセッションのコミット（tasukaru-dev）

```
f56fa7e ガイド常時表示＋OCRステップに記録方法の仕組みをモック追加(guide-method-v1)
9849d31 記録方法でクレカ明細タブ/カード選択肢を出し分け(credit-method-show-v1)
3847f92 CSV方式はOCRクレカの仕訳化を弾く(credit-ocrguard-v1)
cbffb7f クレカ明細タブに仕訳状態フィルタ追加(orico-filter-front-v1)
fb2b48b レシート保管庫ビュー新設＋OCR仕訳紐付け(receipt-vault/link-v1)
```
本番 `tasukaru` へは `19a555d`（Merge）で全件反映。DEV/本番とも実機確認済み（本番はデータ非変更の閲覧＋ガード試行409で副作用なし確認）。


## 15. 利用管理（来所管理）実装＋利用者マスタのセキュリティ調査（2026-06-12 DEV反映済み・本番未反映）<!-- readme-visit-mgmt-v1 -->

このセッションで「利用管理（来所管理）」機能を新規実装し DEV で動作確認まで完了。あわせて利用者登録まわりのセキュリティ問題（Supabaseキーのフロント露出）を発見・調査し、対応設計を固めた（実装は次回）。**いずれも本番未反映**。

### 15-1. 利用管理（来所管理）= デイの「月間サービス計画及び実績の記録」をデジタル化

紙の月間実績表テイストで、利用者ごとに「予定（○/休み✕）」と「実績（出席/振替/休み）」を月間表示する閲覧・確認画面。当初は連絡帳機能の検討から派生し、「いつ誰が来たかを記録してケース記録のし忘れを防ぎたい」という要望で先に着手。

**設計の要点（HIROと確定）**
- **予定**は既存 `patient_visit_days`（weekdays/ampm_per_day）から算出。**移設しない**（曜日設定UIは vitals.html のまま）。曜日コードは **日曜=0〜土曜=6（JS getDay基準）**。Python の weekday() は月=0 なので `(weekday()+1)%7` で変換。
- **休み（✕）**は既存の休み連絡（`records` テーブル、`category="休み連絡"`、`leave_date_start`〜`leave_date_end` の期間、`leave_record_id`）を参照。**新テーブル不要**。✕タップでケース記録へ飛ばす導線（`/daily_view?record_id=` は未検証）。
- **実績**はバイタル連動で自動。**予定曜日にバイタル→出席(present)、予定外にバイタル→振替(transfer)**。バイタル削除で実績も自動削除（その日に他バイタルが無ければ）。手作業ゼロが目標。状態は present/transfer の2つ（当日キャンセル・欠席マークは廃止。予定○で実績が空＝休んだと読む）。
- **休みの実績表示**：実績行に「休」も出す。①休み連絡がある日、②経過済みの予定日でバイタルなし（＝来なかった）。**未来の予定日は空欄**（実績はその日が経過して初めて成立）。
- 画面は**管理者MENU内「利用者管理」タブの先頭にリンクカード1つ**（各利用者カードには置かない）。利用者選択は**記録入力と同じ検索UI**（ひらがな/漢字/カルテ番号、ひらがな⇄カタカナ変換込み）を移植。スマホ横スクロール・PC全日一画面で同一デザイン。

**実装（DEVコミット）**
- `7248c85` フェーズA: `GET /api/visit/month`（月間集約）＋バイタル連動（save_vital/add_vital フックで `_visit_auto_upsert`）＋削除連動（delete_vital で `_visit_cleanup_on_vital_delete`）。marker `visit-mgmt-v1`。
- `1153185` 修正: `visit_records.patient_id` を **bigint→text** に（vitals.patient_id が text=UUID文字列のため）。`int()` を `str()` に。marker `visit-mgmt-idfix-v1`。**DEVで ALTER 実行済み**。
- `bccb17c` フェーズB: 月間実績表ページ `visit.html` ＋ `/visit` ルート（`visit-page-v1`）＋管理者MENU導線（`visit-admin-link-v1`、後に廃止）。
- `cd5f91a` 実績行に休み表示。
- （経過済み予定日→休 の追加コミット）
- `32b231c` 検索UI化（かな/漢字/カルテ番号）＋管理者MENUに集約（各カードのボタン廃止、`visit-admin-menu-v1`）。

**新テーブル `visit_records`（DEV作成済み・本番未作成）**
```sql
CREATE TABLE visit_records (
  id BIGSERIAL PRIMARY KEY, facility_code TEXT NOT NULL,
  patient_id TEXT NOT NULL,  -- patient_profiles.id（UUID文字列）基準。vitalsと揃える
  visit_date DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'present' CHECK (status IN ('present','absent','cancelled','transfer')),
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('vital_auto','manual')),
  checked_at TIMESTAMPTZ, staff_name TEXT, note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (facility_code, patient_id, visit_date)
);
-- ※status の absent/cancelled は現設計では未使用（present/transfer のみ）。本番反映時はこのDDL＋patient_id=text で作る。
```

**DEV検証済み**：月間API（予定/休み/実績集約）、予定日バイタル→出席・予定外→振替、バイタル削除で実績消去（他バイタルが残る日は保持＝設計どおり）、検索UI（かな/漢字/カルテ番号）、管理者MENU導線。テスト用ダミーバイタルは DEV に残置（ダミーデータのため許容）。

### 15-2. 【重要・要対応】利用者登録まわりで Supabaseキーがフロント露出

`admin.html` の利用者**追加・削除・CSV一括取込**の3箇所が、サーバAPIを経由せず**ブラウザから Supabase REST を直叩き**している。そのため `supabase_url` / `supabase_anon_key` がテンプレートに埋め込まれ**フロントに露出**（`const SUPABASE_URL='{{ supabase_url }}'` / `SUPABASE_KEY='{{ supabase_anon_key }}'`）。開発者ツールから鍵を抜けば利用者データに直接アクセス・改ざん可能。**SECRET_KEY露出（§2）と同様に優先対応すべき。**

- 該当箇所（admin.html）：`addPatientProfile()`（POST patient_profiles）、`executeDelete()`（DELETE patient_profiles?id=eq.）、`bulkUpsertPatients()`（CSV、merge-duplicates で patient_profiles に upsert）。
- HIRO も露出回避に同意済み。**今後はキーをフロントに出さない方針で作業する。**

### 15-3. 利用者マスタの二重構造（調査で判明、設計の前提）

- **`patient_profiles` が利用者マスタの正本**。`id`=**UUID**。氏名・ふりがな(`user_name_kana`)・生年月日・`patient_number`・介護度・目標などフル情報。`get_patients()` はこれを主に読む。
- **`patients` は補助テーブル**。`id`=**整数**（=`patient_int_id`）。`user_name` で profiles と紐付き、整数IDの採番用。`patient_visit_days`（曜日設定）・誕生日などが `patients.id` 基準。カナは `user_kana`（profiles は `user_name_kana`、**カラム名が違う**）。
- 利用者を登録するには **両テーブルに行が必要**（profiles=本体、patients=整数ID用）。DEVは51名全員が両方に揃っている（user_name で1対1）。
- **既存サーバAPIの問題**：`/api/add_patient`・`/api/bulk_register_patients`・`/api/delete_patient` は **`patients` にしか書かない**。フロント直叩きは **`patient_profiles`**。単純にAPIへ差し替えると書き込み先が変わり利用者が一覧から消える。→ **APIを profiles 主軸＋patients 連動に作り直す必要がある。**
- 現状の物理削除は profiles だけ消し patients 行が残る（ゴミ）。論理削除（利用中止）は `discontinued_date` で別管理。

### 15-4. CSV取込・写真AI読み取りの検証状況

- 関数は存在（`handleCsvFile`/`bulkUpsertPatients`、`scanPatients`/`registerScannedPatients`/`onScanFileSelect`。後者は `/static/admin.js`）。
- **写真AI読み取り**：サーバ `POST /api/scan_patients_from_image`（Gemini で名簿画像を解析→JSON）。`/api/bulk_register_patients` で登録。1x1ダミー画像では500（不正入力に対する正常な失敗の可能性大）。**実画像での確認は次回**。検証用に**架空名簿PNGを作成済み**（デイサービスさくら、6名、和暦生年月日・利用曜日入り）。
- **CSV取込**：マモルくん形式CSVをフロントでパース（`CSV_COL_MAP`）→ patient_profiles に直叩き upsert（＝15-2の露出箇所）。

### 15-5. 残タスク（次回）

1. **【最優先】Supabaseキー露出の解消**：利用者 追加・削除・CSV取込を **サーバAPI経由（profiles主軸＋patients連動）**に作り替え、`admin.html` から `SUPABASE_URL`/`SUPABASE_KEY` を削除。基幹テーブルなので慎重に（追加・削除・取込が両テーブルに正しく反映され、一覧表示が壊れないことを実機検証）。
2. **写真AI読み取りの実機確認**（架空名簿PNGで読み取り→登録）。
3. **管理者MENU「利用者管理」タブのUI再編**：上から「利用者登録」「利用者一覧・編集」「利用管理」。「利用者登録」を開くと中に「新規手入力登録/CSV取込/写真からAI読み取り」。二段アコーディオンは避け、一段＋タブ切替などスッキリ案をモック提案してから実装。
4. **利用管理ページに戻るボタン**（管理者MENUへ）。
5. （以前からの保留）連絡帳機能本体、ナビのランチャー化（記録=緑/情報共有=紫/帳票管理=オレンジのカテゴリ色分けグリッド、モック承認済み）、ケース記録への「今日の来所者」表示。

### 15-6. このセッションの主なコミット（tasukaru-dev、本番未反映）
```
32b231c 利用管理: 検索UI化＋管理者MENUに集約
cd5f91a 利用管理: 実績行に休みを表示（＋経過済み予定日→休 の追加コミット）
bccb17c 利用管理フェーズB: 月間実績表ページ＋管理者MENU導線
1153185 利用管理フェーズA修正: visit_records.patient_id を text(UUID)対応
7248c85 利用管理フェーズA: 月間集約API＋バイタル連動＋削除連動
ce92aba docs: §14 追記
```
**本番反映時の注意**：本番 Supabase に `visit_records`（patient_id=text 版）を作る DDL が先行で必要。


## 16. 利用者管理 Supabaseキー露出の解消（2026-06-14 本番反映完了）<!-- readme-keyexposure-done-v1 -->

§15-2 で要対応とした **admin.html の利用者 追加・削除・CSV取込の Supabaseキー直叩き露出**を解消し、**DEV検証 → 本番(cocokaraplus-5526)反映まで完了**した。DDLは無し（コードのみ）。

### 16-1. 実施内容

- **サーバAPI 3本を新設**（app.py、marker `admin-patient-api-v1`、`bulk_register_patients` ルート直前に挿入）:
  - `POST /api/admin/patient/add` … 1名手入力登録
  - `POST /api/admin/patient/delete` … 1名削除
  - `POST /api/admin/patient/bulk_import` … CSV一括取込（upsert / merge-duplicates相当）
  - いずれも `@login_required`。`facility_code` は**サーバ側で `session["f_code"]` を強制適用**し、フロント由来の値は信用しない（なりすまし防止）。
  - 削除は `id` + `facility_code` の**二条件**で、ログイン施設のレコードのみ削除可。
- **admin.html**（marker `admin-patient-front-v1`）:
  - `SUPABASE_URL` / `SUPABASE_KEY` の定義を**削除**（`FACILITY_CODE` は他で使うため残置）。
  - `addPatientProfile()` / `executeDelete()` / `bulkUpsertPatients()` の `fetch` を上記サーバAPIに差し替え。CSVのパース処理（和暦変換・カナ変換・`CSV_COL_MAP`）はフロントに残し、できた配列を送る形＝**挙動は現状と同一**。
  - admin の `render_template` から `supabase_url` / `supabase_anon_key` の受け渡しを削除。

### 16-2. 採用した方針と、当初計画(§15)との差分【重要】

- **今回は「方針A: `patient_profiles` のみ操作・現状挙動を維持」で実施した。**
- §15-3 / §15-5 が想定していた「**profiles主軸＋patients連動**（=方針B）に作り替える」は**今回スコープ外**。理由: 今回の主目的は**キー露出の解消**であり、基幹2テーブルの同時書込（連動）を同じ変更に混ぜると検証範囲が広がり事故リスクが上がるため、純粋な「書込経路をサーバへ移すリファクタ」に限定した。
- したがって §15-3 に記載の「単純にAPIへ差し替えると書き込み先が変わり一覧から消える」という懸念は**発生しない**（書込先は従来同様 `patient_profiles` のまま）。

### 16-3. DEV検証（Chrome MCP・DEMO001）

- キー定義消滅・`/rest/v1/...`直叩き消滅・marker存在を確認。
- 追加（API直叩き / 実UIボタン経由の両方）・CSV取込（2件）・削除すべて200 success。
- **facility_code強制上書きを実証**: `facility_code:'EVIL999'` を混ぜて送っても DEMO001 として保存された。
- 検証データは全削除し DEMO001 はクリーン状態に復帰。本変更起因のJSコンソールエラーなし。

### 16-4. 残課題（次セッション以降）

1. **他テンプレートの anon_key 露出**: `anon_key` をフロントに渡す箇所が admin.html 以外にも複数ある（`patient_profile.html` の render〔app.py 7799行付近〕、ほか app.py 1901行・9671行付近）。同様に直叩き露出の可能性が高く、今回のパターン（`/api/admin/...` + facility_code強制上書き）を流用してサーバAPI化する。
2. **二重構造の連動（方針B）= 今回未対応**: 手入力・CSVで追加した利用者は `patient_profiles` のみに入り `patients` には連動しない。`patients` 参照系の画面（バイタル・利用管理・`patient_visit_days` 等）に**新規利用者が出てこない**問題が起きうる。発生したら方針B（profiles書込時に patients 連動作成）+ **既存データのバックフィル**で対応。
   - 連動ロジックの既存実装が参考になる: `add_today_patient`（app.py、patients+visit_days を連動作成）、`api_bulk_register_patients`（同）。
   - **DEVと本番は別Supabaseプロジェクト**。データのバックフィルはそれぞれに対して別個に調査・実施が必要（コード修正はマージで両ブランチに反映されるが、既存データの不整合はコードでは直らない）。
3. §15-5 の残り（写真AI読み取りの実機確認 / 利用者管理タブUI再編 / 利用管理ページの戻るボタン / 連絡帳・ナビランチャー化）は引き続き未対応。

### 16-5. このセッションのコミット
```
a3f10f1 (tasukaru-dev) 利用者管理: Supabase直叩きをサーバAPI化、anon_key露出を解消 (admin-patient-api-v1)
ede09ed (tasukaru)     ↑を本番へマージ反映
```


## 17. キー露出 第2弾: patient_profile 解消 + Realtime露出の切り分け（2026-06-14 本番反映完了）<!-- readme-keyexposure-2-v1 -->

§16-4-1 で挙げた「他テンプレートの anon_key 露出」を調査し、**直叩き(REST)型は解消・Realtime型は別課題として切り分け**た。

### 17-1. 調査結果: 露出は2種類に分かれる

`anon_key` をフロントに渡すテンプレートは admin.html(§16で解消済)以外に3つ。用途で対応が分かれた:

| テンプレート | キー用途 | 対応 |
|---|---|---|
| `patient_profile.html` | **REST直叩き**(保存/削除/一括取込) | **今回サーバAPI化で解消** |
| `chat_room.html` / `chat_rooms.html` | **Supabase Realtime購読**(websocket) | **保留**(別課題) |
| `board.html` | **Supabase Realtime購読**(websocket) | **保留**(別課題) |

Realtime型は `supabase.createClient(URL, KEY)` で websocket を張り `postgres_changes` を購読しており(新着投稿/メッセージの即時表示)、**サーバAPI化では解消できない**(websocketはブラウザから直接張る必要がある)。根本対策(自前WS中継 or 署名トークン発行等)は重く、今回スコープ外。

### 17-2. patient_profile.html の解消（実施・本番反映済み）

- **新設API** `POST /api/admin/patient/save`(app.py、marker `admin-patient-save-v1`、delete route直前):
  - `id`あり=update / `id`なし=insert。`facility_code`はサーバ側で`session["f_code"]`強制。update は `id`+`facility_code`二条件。新規時は採番した`id`を返す。
  - フロントが組み立てたフィールドをそのまま通す方式(フィールド追加に強い／現状挙動を維持)。
- **削除・一括取込は §16 の既存API**(`/api/admin/patient/delete`・`/bulk_import`)を**再利用**。
- **patient_profile.html**(marker `patient-profile-front-v1`): キー定義削除、保存/削除/一括取込の`fetch`を上記APIに差し替え。保存後の patients 同期(`/api/update_patient_birth`、既存サーバAPI)はそのまま残置。
- app.py の patient_profile render から `supabase_url`/`supabase_anon_key` 受け渡しを削除。
- **DEV検証(Chrome MCP・DEMO001)**: 保存(新規→ID採番／更新→内容反映)・削除・facility_code強制上書き、すべて確認。検証データは全削除。JSエラーなし。

### 17-3. チャット機能(chat)の現状と扱い【重要・保留】

HIRO 認識では「過去に実装したが今は使っていない」機能。**しかしルート・関数は生存しており、URL直打ちで開ける＝キーは露出したまま**(導線を消しただけ)。

- 生存ルート: `/chat`(`def chat`→`chat_rooms.html`)、`/chat/<room_id>`(`def chat_room`→`chat_room.html`)、`/api/create_room`・`/api/send_room_message`・`/api/delete_room_message`。
- 使用テーブル: `chat_rooms` / `chat_messages` / `chat_members`。
- **チャット外からの依存(削除の障害)**:
  1. **バイタルアラート自動通知**(app.py 2412行付近): バイタル異常値検出時に全スタッフ共有チャットルームへ「再検査が必要」を自動投稿。`try/except`保護あり。
  2. **未読数集計API**(app.py 3711行付近、`chat_members`/`chat_messages`参照): ナビ等のバッジ用と推測。
- **判断(このセッション)**: 事故回避のため**今は一切触らない**(コード・名前ともそのまま)。命名(`chat`が役割と不一致)の整理や削除は、上記依存を解いてから別セッションで行う。
- board.html も同様に Realtime キー露出ありだが、掲示板は現役機能なので削除対象ではない。Realtime露出の根本対策は将来課題。

### 17-4. 残るキー露出(次セッション候補)
- `chat_room.html` / `chat_rooms.html` / `board.html` の Realtime用 anon_key 露出(上記の通り根本対策が必要)。
- §16-4-2 の二重構造連動(方針B)＋データバックフィルは引き続き未対応。

### 17-5. このセッションのコミット
```
d37ea73 (tasukaru-dev) 利用者情報: patient_profile.htmlのSupabase直叩きをサーバAPI化 (admin-patient-save-v1 / patient-profile-front-v1)
aadb96c (tasukaru)     ↑を本番へマージ反映
```


## 18. 二重構造(profiles↔patients)問題の原因確定と方針B確定スコープ（2026-06-14 調査のみ・実装は次回）<!-- readme-dual-structure-v1 -->

§16-4-2 で保留した「追加した利用者がバイタル等に出てこない」二重構造問題を**DEVで実機調査し、原因と対策スコープを確定**した。**実装は未着手**(次セッション)。

### 18-1. 原因の確定（バイタル画面で検証）

- `get_patients()`(app.py 169行)は **`patient_profiles` 主軸**でリストを作り、`patients` の整数IDを `user_name` マッチで `patient_int_id` として付与する。**patientsに対応行が無ければ `patient_int_id = null`**。
- `vitals.html` の `renderPatientList()`(1543行付近)は、`AMPM_PER_DAY[p.id]`(=`patient_visit_days` 由来、`patient_int_id` 経由で紐付く)を見て、**今日の曜日が 'NONE'(曜日設定なし)の利用者を `return false` で非表示**にする。
- 結論: **profilesのみに追加した利用者(=patient_int_id null)は patient_visit_days を持てず、バイタル画面に表示されない**。サーバHTMLには `{% for p in patients %}` で全員カードが埋め込まれるが、JS描画時に曜日フィルタで隠れる二段構造。
- 同様に `patient_int_id` / `patient_visit_days` 依存の画面(記録入力・利用管理 等)でも不整合が起きると推測。

### 18-2. 孤児調査の結果（重要: バックフィル不要）

`get_patients` の結果(`PATIENTS` 変数)から `patient_int_id == null` を孤児として非破壊カウント:

| 環境 | 総利用者 | 孤児(patients未連動) |
|---|---|---|
| DEV (DEMO001) | 51 | **0** |
| 本番 (cocokaraplus-5526) | 72 | **0** |

→ **両環境とも既存データに孤児なし。既存分のバックフィルは不要**。これまでの登録は patients も作る経路(`add_today_patient`・`api_bulk_register_patients` 等)で行われてきたため健全。

### 18-3. 方針B 確定スコープ（次セッションで実装）

- **孤児が生まれるのは、今回キー露出解消で新設した `add`/`save`(新規)/`bulk_import` が「profilesのみ書く」ため**。よって方針Bは**新規追加時の patients 連動の実装が主**(既存修復は不要)。
- **第1段(次回実装)**: `add`・`save`(新規)・`bulk_import` で profiles 書込後に `patients` 行を連動作成(`user_name`/`user_kana`/`birth_date`/`chart_number`)。手本=`api_bulk_register_patients`(app.py 7614行付近)。これで「追加した利用者が後から曜日設定できる(=バイタルに出せる)」状態になる。
- **第2段(将来)**: 登録UIに曜日入力欄を統合し、登録と同時に `patient_visit_days` も作る(HIRO談: 登録時に曜日も決まっていることが多い)。UX改善で急ぎでない。
- **表示ロジック変更案は不採用**: `renderPatientList` の NONE フィルタを緩める案もあるが、現場の曜日絞り運用に影響するため書込側で連動する方針を採る。

### 18-4. 実装前に確認すべき論点（次回最初に）

- **`patients.chart_number`(NOT NULL)の採番方法**: profiles の `patient_number` を流用するか独自採番か。既存利用者で `patients.chart_number` と `patient_profiles.patient_number` がどう対応しているか(一致/別物)を先に確認してから実装する。
- 連動は新規(insert)時のみ。`save` の更新(id有り)は patients 既存前提で連動不要。

### 18-5. このセッションでの作業
- 調査のみ(コード変更なし)。DEVで検証用利用者の追加→削除を実施しクリーンに復帰。本番は非破壊参照(PATIENTS読取)のみ。


---

## 19. 次セッションへの引き継ぎ（2026-06-14〜15 セッション完了時点）<!-- readme-handover-2026-06-15 -->

**このセクションは、新しいチャットに切り替わった次の Claude が、HIROから改めて説明を受けなくても作業に入れることを目的に書かれている。まずここを読んでから動くこと。**

### 19-1. 絶対に守る運用ルール【最優先】

**セキュリティ最優先。キー・シークレットの扱い:**
- `SUPABASE_URL` / `SUPABASE_KEY` / `SECRET_KEY` / 各種APIキー等の値を、**コード・ログ・ターミナル出力・チャット応答のどこにも生で出さない**。
- 値を表示・確認する必要がある場合は必ずスクランブル(マスキング)する。例: `eyJ...****...XyZ` のように先頭数文字+末尾数文字だけ表示し、中間は伏せる。**全体は決して出さない**。
- フロント(テンプレート)へキーを渡す設計は今後も避ける。サーバAPI化、もしくは Realtimeをポーリングへ置換、で対応してきた(§16〜18+本セクション)。

**ファイル受け渡しの方法(これが標準フロー):**
- HIROのローカル: `/Users/ZIMAX 1/dev/kaigo-ai-app/`(Mac, VSCode)。
- Claudeが既存ファイル(`app.py`, テンプレート, README等)を見たいとき、**VSCodeのターミナルで実行する `cp` コマンドを Claude が提示**する。HIROはそれを実行し、`~/Downloads/` に出たファイルをチャットに添付する。
  - 例: `cp ~/dev/kaigo-ai-app/app.py ~/Downloads/`
  - 日本語ファイル名はワイルドカード推奨: `cp ~/dev/kaigo-ai-app/README_TASUKARU_*.md ~/Downloads/`
- Claudeの成果物(パッチ等)は `/mnt/user-data/outputs/` に出力し、present_files で提示。HIROがDownloads経由でリポジトリに配置 → コミット。
- コードはチャットに直貼り/heredoc禁止。**冪等パッチ.py** (marker+`.bak`+`assert count==1`)を作って渡し、HIROが実行する形に統一。

**開発ルール(引き続き厳守):**
- パッチは `marker` で冪等性を担保し、`assert src.count(anchor)==1` でアンカー一意性を検証してから当てる。`.bak_YYYYMMDD_HHMMSS` で自動バックアップ。
- 検証: app.py は `python3 -m py_compile`、htmlは div均衡 + Jinja除去後 `node --check`。**サンドボックスで通してから渡す**。
- ブランチ: `tasukaru-dev`(DEV) → `tasukaru`(本番) の**一方向マージ**。作業後は `git checkout tasukaru-dev` に戻る。
- DDLがある変更は、Supabase DEV/本番の両方に**先に**適用してからコード本番マージ。今回のセッションは全てコードのみでDDL無し。
- 日本語で応答。grep/sed anchorに日本語を直接書かない(エスケープ表記)。挿入する文字列・コメントは日本語可。
- 「新しいガードが想定外の挙動」になったら、まずデプロイ未完了/Cloud Runインスタンス混在を疑う。
- 文字列の `includes` 確認だけで削除完了と判断しない(同名・文脈違いで誤一致する)。テーブルの実IDで対象を取って確実に消す。

### 19-2. プロジェクト基本情報

- TASUKARU(介護施設管理SaaS)。Flask + Supabase + Google Cloud Run、asia-northeast1。運営 合同会社LIFE PLUS。
- リポジトリ: `cocokaraplus-max/kaigo-ai-app`。
- DEV施設: `DEMO001`(Supabaseプロジェクト `otjevnmoycnvaxeltrtj`)。
- 本番施設: `cocokaraplus-5526`(Supabaseプロジェクト `abvglnkwtdeoaazyqwyd`、実運用中)。HIROの「もみの木接骨院」併設のデイサービス。
- **DEVと本番は別Supabaseプロジェクト**。コード修正はマージで両ブランチに反映できるが、既存データの不整合はコードでは直らない。データ補正は各プロジェクトに対して個別に実施。

### 19-3. このセッションの全成果(本番反映完了)

セキュリティ系のキー露出を全テンプレートで解消し、二重構造問題に方針Bの実装を入れた。本番反映済み。

**(a) キー露出の完全解消**

| テンプレート | 用途 | 解消方法 | マーカー |
|---|---|---|---|
| `admin.html` | 利用者 追加/削除/CSV取込 (REST直叩き) | サーバAPI化 `/api/admin/patient/add` `/delete` `/bulk_import` | admin-patient-api-v1 / admin-patient-front-v1 (§16) |
| `patient_profile.html` | 利用者情報 保存/削除/一括取込 (REST直叩き) | サーバAPI化 `/api/admin/patient/save` (新規でID返却)、delete/bulk_importは再利用 | admin-patient-save-v1 / patient-profile-front-v1 (§17) |
| `chat_room.html` | チャット (Realtime購読) | キー定義を空文字化 → 既存の pollFallback(`/api/new_messages`)に自動切替 | chatroom-key-front-v1 / chatroom-key-render-removed-v1 |
| `board.html` | 掲示板 (Realtime購読) | キー定義空文字化 + startRealtime を `/api/board/unread_count` 10秒ポーリング+リロードに置換 | board-key-front-v1 / board-key-render-removed-v1 |

サーバAPIは全て `@login_required` + `facility_code = session["f_code"]` 強制(なりすまし防止)、削除は `id`+`facility_code` 二条件でログイン施設のみ。

**(b) 方針B 第1段: 利用者追加時の patients 連動**

- ヘルパ `_ensure_patient_row(supabase, f_code, profile_row)` を新設し、`add` / `save`(新規) / `bulk_import` の3経路で profiles 書込後に呼び出し(marker `patients-sync-b1`)。
- `patients` 行を `user_name`(マッチ用)、`user_kana`(profilesの`user_name_kana`から)、`birth_date`、`chart_number` で作成。**`chart_number` は profiles の `patient_number` をコピー**(紙の正本と一致するルール、§17調査で確定)。
- 同名 patients 行があれば作らない(重複防止)。patient_visit_days(曜日)は第1段では作らない。
- 利用者番号の整形ヘルパ `_normalize_patient_number()` も追加(marker `patient-number-zerofill-v1`)。数字のみなら**最低3桁ゼロ埋め**(62→062、9→009、3桁以上はそのまま、英字付きは触らない)。大規模施設で自然に4桁化しても破綻しない設計。

**(c) DEVデータ整理**

- 「タスカルちゃん」(patients id=51、HIROが意図的に置いたサンプル)が逆方向孤児(profilesなしpatients)だったため、profilesに `D051` で追加+patients側も `D051` に更新して紐づけ完了。DEMO001は順方向孤児ゼロ・逆方向孤児ゼロ。
- 本番(cocokaraplus-5526)も順方向孤児ゼロ。逆方向孤児に見えた7名(石川信行、井上智子、宇井静子、鈴木義路、嶺村竹男、宮田鈴子、横地美恵子)は**利用一時停止中**の方々で、`is_discontinued`フラグが立っているため `get_patients`(現役のみ)のリストには出ないが profilesにも patientsにも存在し健全。再開は中止フラグを外すだけで番号・記録ともそのまま引き継げる。

### 19-4. 重要な調査結果(コード読解で確定済み)

**get_patients の仕組み(app.py 165行付近):**
- profiles 主軸でリストを作り、user_name で patients とマッチして `patient_int_id` を付与。
- マッチしなければ `patient_int_id = null`(=孤児)。

**バイタル画面の利用者フィルタ(vitals.html `renderPatientList` 1543行付近):**
- `AMPM_PER_DAY[p.id]` の今日の曜日が `'NONE'`(曜日設定なし) → `return false` で**非表示**。
- HTMLには `{% for p in patients %}` で全員カードが埋め込まれるが、JS描画時に曜日フィルタで隠れる二段構造。
- 結論: profilesのみ追加の利用者(=patient_int_id null) → patient_visit_days を持てない → バイタルに出ない。これが§18で確定した二重構造問題の正体。

**カルテ番号(`patients.chart_number`)の運用実態:**
- 画面検索で使われる「カルテ番号」は `get_patients` が profiles の `patient_number` を `chart_number` フィールドに入れて返すもの。**実は profiles の patient_number 側**。
- `patients.chart_number` は画面表示・検索にほぼ使われない補助値。本番で4名(板倉/柴田/松岡/宮浦)が紙より1ずれているが実害なし。
- あいまい検索は部分一致なのでゼロ埋めの有無は実害なし(「62」で「062」もヒット)。
- `/api/patient_profile/get_by_patient_number`(完全一致API、7802行)は本セッションの調査範囲ではどこからも呼ばれていなかった。

**チャット機能(chat)の現状:**
- HIROが過去に実装したが**現在は使っていない**(UIから外したのみ、ルートと関数は生きている)。
- バイタル異常時のアラート自動通知(app.py 2412行付近)と未読数集計(3711行付近)からまだ参照されている。安易に削除できない。
- chat_room.html に既存のJSエラー `toggleMembers is not defined`(本セッションの変更とは無関係)があり、再開するなら直す。

### 19-5. 残課題(優先度順)

1. **掲示板の確認ボタン挙動**: 「確認済みボタンが未確認に戻る」と現場報告。サーバ保存もDEV動作も正常で再現性なし、**様子見**。再発時に「いつ・誰が・どの投稿で・直前に何をしたか」をメモしてもらう。怪しい箇所: `toggle_check` (app.py 9956行)に facility_code 条件がない(unread_count とは非対称)。同名スタッフは「いない」と HIRO 確認済みなので最有力候補ではないが、保険として条件を揃える改修は低リスク。
2. **方針B 第2段**: 登録UIに曜日入力欄を統合(HIRO談「登録時に曜日も決まっていることが多い」)。登録と同時に `patient_visit_days` も作れば、追加直後からバイタルに出る完全な体験になる。UX改善で急ぎではない。
3. **削除時の逆向き孤児**: 利用者を削除すると profiles は消えるが patients が残る(`/api/admin/patient/delete` は profilesのみ削除)。HIRO 運用は「中止フラグ(is_discontinued)」中心なので発症頻度は低く、影響軽微(`get_patients` は profiles 主軸なので画面に出ない)。
4. **本番の既存カルテ番号ズレ補正(任意・気持ちよさのみ)**: 値ずれ4名(板倉/柴田/松岡/宮浦)と、ゼロ埋め差15名。検索への実害なし確認済み。直すなら `update patients set chart_number = ... where facility_code='cocokaraplus-5526' and id=...` のピンポイントSQLで安全に可能。
5. **チャット機能の整理(命名・削除)**: 機能整理する場合、バイタルアラート通知と未読バッジの依存解消が先。命名(`chat`が役割と不一致)はその後。
6. **§15-5 持ち越し**: 写真AI読み取りの実機確認、利用者管理タブのUI再編、利用管理ページの戻るボタン、ナビのランチャー化など。

### 19-6. このセッションのコミット(本番反映済み)

```
a3f10f1 / ede09ed: §16 admin Supabase直叩きをサーバAPI化
d37ea73 / aadb96c: §17 patient_profile Supabase直叩きをサーバAPI化
ca313b1 / b2260a4: B1 利用者連動 patients-sync-b1
1cbb5f7 / b2260a4: B1 番号ゼロ埋め patient-number-zerofill-v1
811c818 / fa49c7e: chat_room キー解消(ポーリング切替)
8269e6a / fa49c7e: board キー解消(unread_count ポーリング)
```

### 19-7. 引き継ぎ後の最初の一手(おすすめ)

次セッション開始時、HIROから具体的な指示が無ければ、以下のどれかを提案するのが筋。

- **残課題(1)掲示板確認ボタン**: 再発があれば原因の絞り込みから、なければ低リスクな保険修正(toggle_check に facility_code 条件追加)だけ入れる選択肢を提示。
- **残課題(2)方針B第2段**: 登録UIに曜日欄を入れる設計から。モック提案→承認→実装の順。
- **残課題(4)カルテ番号ズレ補正**: HIROの「気持ち悪い」を解消したいなら、本番のピンポイントUPDATE SQLを用意して実行してもらう。

HIROは「おまかせ」「おすすめで」と言ってくれることが多い。その場合は理由を添えて1つ推奨し、リスクと判断材料を提示してから進める。慎重に、しかし手は動かす。


---

## 20. 出納帳・現金補填まわりの一連の改修（2026-06-16 セッション）<!-- readme-ledger-session-2026-06-16 -->

このセッションは会計モジュールの「現金出納帳・現金自動補填」を集中的に直した。**(A)本番反映まで完了した修正群** と、**(B)次セッションで実装する大型ロジック(累積現金補填)の確定設計** に分かれる。まず(B)の設計を理解してから着手すること。

### 20-1. 事業構成と現金補填の前提（最重要・このモジュールの背景）

- 本番施設 `cocokaraplus-5526` は事業部(`ledger_divisions`)で分かれる。**id=1 接骨院 / id=2 半日型デイサービス / id=3 1日型デイサービス**。DEV(DEMO001)も同じ3事業部・同じidが入っている。
- 現金の流れ: **デイサービスは売上が銀行振込中心で手元現金が入らない。接骨院は窓口一部負担金で現金が入る。** その接骨院の現金を物理的にデイサービスへ回して消耗品等を買う。
- よって帳簿上も「**接骨院=出金 / デイサービス=入金**」の事業間移動(科目199 事業間移動)の対で記録するのが正。接骨院自身の経費は接骨院の売上/普通預金で賄うため**補填対象外**。
- 勘定科目: 101 現金 / 102 普通預金 / 199 事業間移動 / 300 事業主借。**103は売掛金**(普通預金ではない)。「銀行から現金を下ろす」貸方は **102のみ**(HIRO確認済み)。
- 設定: `ledger_settings.auto_cash_fill`(補填ON) / `cash_fill_division_id`(補填元=接骨院id=1) / `divisions_enabled`(事業部管理ON)。本番は3つとも有効。**DEVは divisions_enabled が false の時があり、その場合は仕訳モーダルに事業部欄が出ない**(設定の歯車トグルでON)。

### 20-2. このセッションで本番反映完了した修正（A群）

| marker | 内容 | ファイル |
|---|---|---|
| cashfill-per-division-v1 | 現金補填を**事業部別・移動先別**に。補填元(接骨院)以外の各事業部について「その事業部の現金経費 − 普通預金引出」の不足分を、接骨院→当該事業部の事業間移動の対(出金/入金)で立てる。旧実装は入金側が division_id=null でどの出納帳にも乗らず、全事業部を合算した1本だった(これがHIROの違和感の正体)。 | app.py |
| bankcash-102only-v1 | 銀行引出判定を 102/103 → **102のみ**(103=売掛金を除外)。 | app.py |
| cashfill-allcash-v1 | 補填対象を「貸方=現金 かつ 借方=費用」→「**貸方=現金の取引すべて**」に拡張。費用だけでなく預り金(個人市県民税など)の現金支払いも補填対象に。引出は借方=現金なので混入しない。 | app.py |
| subledger-inout-sort-v1 | 現金/預金出納帳の同一日付内表示を「**入金→出金**」順に(表示のみ)。 | ledger.html |
| subledger-monthnav-fix-v1 | 月切替が現金/預金/売上/クレカタブで効かない不具合を修正。changeMonth がアクティブタブに応じて再読込。 | ledger.html |
| subledger-pdf-blob-v1 | PDF保存が「表示されるだけで保存できない」不具合を修正。a target=_blank → fetch+Blob+download。 | ledger.html |
| ledger-excel-styled-v1 | 出納帳/試算表のExcel出力を無料版SheetJS(スタイル不可)→**exceljs**に載せ替え。ヘッダー背景+太字、全セル罫線、入金=薄青/出金=薄赤、合計行=太字+薄グレー、金額#,##0。exceljsはcdnjsから動的読込。 | ledger.html |
| ledger-backtotop-v1 | 出納帳の全タブに「TOPへ戻る」FAB。**スマホ幅のみ**表示、少しスクロールで出現、最上部へ。スクロール対象は動的判定(window.scrollToが効かず .page-wrapper を使う経緯あり)。既存FAB(.fab-add bottom:140px)と重ならないよう bottom:200px相当+safe-area。 | ledger.html |
| ledger-receipt-entry-api-v1 / ledger-ocr-dup-guard-v1 | OCRレシートの**重複仕訳防止**。OCRプレビューの「この内容で仕訳を作成」を仕訳済みレシートで再度押すと、新API `/api/ledger/receipt_entry?receipt_id=` で既存仕訳を検出し「上書き/キャンセル」確認。上書き=既存仕訳を編集モードで開く(UPDATE)、キャンセル=何もしない。 | app.py + ledger.html |
| ledger-recalc-lock-v1 | **二重補填の根本対策**。`_ledger_recalc_day` を施設単位ロックで直列化(`_ledger_recalc_locks`、既存 `_monitoring_gen_lock` と同方式)+冪等化(削除直前にDBから当日auto_fill/transferを再取得して全削除)。関数を `_ledger_recalc_day`(ロック付ラッパー)と `_ledger_recalc_day_inner`(本体)に分離。本番で5並列保存しても補填が4件(2組)のまま増えないことを実証。 | app.py |

**本番データ補正(SQL)**: `ledger_settings.cash_fill_division_id = 1`(接骨院) を本番に設定。2月分の旧補填仕訳8日分(division=null・事業主借)を、対象日の手動仕訳を無変更で再保存して `_ledger_recalc_day` を走らせ、新ロジックで立て直した(接骨院の経費日=補填ゼロ、半日型の日=接骨院→半日型の対)。

### 20-3. _ledger_recalc_day の現在の仕様（A群反映後）

- 補填ON & cash_fill_division_id あり: 補填元以外の各事業部について `_expense_for(div)`(貸方=現金の全取引) − `_bank_to_cash_for(div)`(借方=現金×貸方=102) の不足分>0 のとき、接骨院→当該事業部の事業間移動の対を立てる。
- **計算は target_date 単位(その日だけ)**。前日からの現金残高は繰り越さない。← これが20-4で作り変える点。
- 既存auto_fill/transfer はロック下で全削除してから立て直す(冪等)。

### 20-4. 【次セッションで実装】累積現金補填ロジック（決算期ベース）— 確定設計

**動機(HIROの要望)**: 現状は日単位独立計算なので、「前日に普通預金から現金を引き出して入力しても、翌日の補填が見直されず、接骨院補填が鎮座したまま」になる。手元現金は翌日以降に繰り越して使えるべき。引き出しを入れたら、その現金でまず払い、足りない分だけ接骨院から補填、という挙動が理想。

**確定仕様(HIROと合意済み)**:
1. **現金残高は事業部ごとに累積管理**(半日型・1日型それぞれ独立。接骨院は補填元なので別)。
2. **累積残高ベースの補填**: 各事業部について、期初残高から日付順に「普通預金引出 + 接骨院補填 − 現金支出」を積み上げ、**現金残高がマイナスに落ちる日に、その不足分だけ**接骨院から補填する。前日までの引出残高が繰り越されるので、引出を入れれば翌日以降の補填が自動で減る/消える。
3. **決算月の設定項目を新設**。弊社(合同会社LIFE PLUS)は**10月決算**(期初=11月、事業年度=11月〜翌10月)。**法人単位で1つ**(全事業部共通)。
4. **決算確定ボタンを新設**。押すとその決算期が「確定」状態になり、確定済み期への入力・編集をしようとすると**保存しようとした瞬間にアラート**(金額などを伝える)。押す前は自由に入力・再計算できる。**ボタンは解除も可能**。
5. **決算ボタンを押していない場合は、決算月を越えても次月へ繰り越す**(決算月で自動リセットしない。実際の締めはボタンが制御)。
6. **期初残高は前期末残高を引き継ぐ**。最初の期はゼロ開始。
7. 実態として介護は「使う分だけ補填」=月末残高ほぼゼロなので、再計算は変更月+せいぜい翌月で収束し重くならない。

**必要なDDL(DEV/本番 両方に先に適用)**:
- `ledger_settings` に決算月カラム(例 `fiscal_year_end_month` int, 既定10)。
- 決算確定の管理(おすすめ: 専用テーブル `ledger_fiscal_closes`(facility_code, period_label or period_end, is_closed, closed_at, released_at...))。期ごとに確定/解除を記録できるようにする。

**実装の要点**:
- `_ledger_recalc_day`(日単位)を、**決算期内を累積で立て直す**方式に作り変える。トリガー(経費/引出の入力・編集・削除)時、変更日からその決算期内(未確定なら現在まで)を日付順に再計算して各日の補填を立て直す。
- 確定済み期に影響する変更は自動反映せず、保存時アラートで金額を提示。
- 月またぎ・期またぎの残高引き継ぎを正しく扱う。
- ロック(ledger-recalc-lock-v1)は引き続き必須(累積でも競合防止が要る)。

**既存データ移行**: 新ロジック投入後、現決算期(2025-11〜2026-10)の全補填を累積で立て直す(2月の立て直しと同じ要領だが期全体)。慎重に。

**検証すべきパターン(DEV)**: 複数月にまたがる繰り越し / 複数事業部独立 / 前日(前月)引出が翌日(翌月)補填を減らす / 決算月をまたぐ繰り越し / 決算確定ボタン押下後のアラート / 確定解除後の再計算。

### 20-5. 残タスク（このセッションで未着手・次回以降）

1. **累積現金補填ロジック(20-4)** — 最優先の大型タスク。設計は確定済み、DDL→実装→DEV検証→本番→移行の順。
2. **領収書の削除・編集** — OCR取込画面と保管庫の両方から、取り込んだ領収書(receipts)を削除・編集できるようにし、仕訳にも反映する。削除時に紐付く仕訳をどうするか(残す/消す)、編集を仕訳へどう反映するかの仕様詰めが必要。HIRO要望: 「一旦取り込んだ領収書を削除、OCR取込画面や保管庫から編集・削除可能に、その後仕訳表に反映」。
3. (継続) §19の残課題、§18方針B第2段 など。

### 20-6. このセッションのコミット（すべて本番反映済み）

```
cashfill-per-division-v1 / bankcash-102only-v1 / cashfill-allcash-v1
subledger-inout-sort-v1 / subledger-monthnav-fix-v1 / subledger-pdf-blob-v1
ledger-excel-styled-v1 / ledger-backtotop-v1
ledger-receipt-entry-api-v1 / ledger-ocr-dup-guard-v1
ledger-recalc-lock-v1
```

### 20-7. 申し送り（運用メモ）

- `git checkout` のたびに `M README.md` が出る状態が続いている(別件の未コミット変更)。次回 `git status` / `git diff README.md` で中身を確認し、コミットか破棄か決めるとよい。今回作業とは無関係。
- DEV検証用のダミーデータ(2026-06-15/16 の半日型・1日型 検証仕訳、ダミー領収書ダイソー/コメリ)がDEVに残っている。実害はないが、気になれば掃除。
- ダミー領収書はClaude側でPillow生成(現金払い・消耗品)。OCR検証に再利用可。


---

## 21. 累積現金補填ロジック（決算期ベース）の実装と本番移行（2026-06-16 セッション後半）<!-- readme-ledger-session2-2026-06-16 -->

セクション20の続き。現金自動補填を「単日計算」から「決算期内の累積残高」ベースに作り変えた大改修。**累積本体は本番反映・既存データ立て直しまで完了**。残るは決算確定ボタンと領収書削除・編集。

### 21-1. 動機（HIROの要望）

旧ロジック(_ledger_recalc_day, 単日)は「その日の現金経費 − その日の普通預金引出」の不足を毎日補填していた。そのため**前日に普通預金から引き出した現金が翌日に繰り越されず**、引出を後から入力しても翌日の接骨院補填が見直されなかった(「補填金額が鎮座」問題)。手元現金は翌日以降に繰り越して使えるべき、というのが要望。

### 21-2. 確定設計（HIROと合意済み）

1. **現金残高は事業部ごとに累積管理**(接骨院=補填元は対象外)。
2. **累積残高ベース補填**: 期初残高を起点に日付順に「普通預金引出+接骨院補填−現金支出」を積み上げ、残高がマイナスに落ちる日に**不足分だけ**接骨院から補填。前日繰越がある限り消化してから補填。
   - アルゴリズム: 不足 = 当日現金支出E − (前日繰越B + 当日普通預金引出W)。不足>0→補填(残高0)、不足≤0→補填なし(残高=(B+W)−E繰越)。
3. **決算月**(会社ごと可変、弊社=10月決算→期初11月)。`fiscal_year_end_month`。法人単位で1つ。
4. **決算確定ボタン**(未実装): 押すと期を締め、確定済み期への変更は保存時アラート。解除可。**押すまでは決算月をまたいでも繰越継続**。
5. **期初残高は前期末を引き継ぐ**(初回はゼロ/手入力、以後は決算確定時に翌期へコピー予定)。
6. 介護は使う分だけ補填=月末残高ほぼ0なので、再計算は変更月+翌月程度で収束し軽い。

### 21-3. DDL（DEV/本番 両方適用済み）

- `ledger_settings.fiscal_year_end_month` int 既定10
- `ledger_fiscal_closes`(id, facility_code, period_end date, is_closed bool, closed_at, released_at) ※決算確定用、まだ未使用
- `ledger_opening_balances`(id, facility_code, division_id, period_start date, amount bigint, updated_at, unique(facility_code,division_id,period_start)) ※期初残高
- `ledger_monthly_balances`(id, facility_code, division_id, ledger_type text, month text, amount bigint, updated_at, unique(facility_code,division_id,ledger_type,month)) ※月初残高

### 21-4. 実装（全て本番反映済み）

| marker | 内容 | ファイル |
|---|---|---|
| ledger-fiscal-month-api-v1 / -ui-v1 | 決算月の設定(設定画面に1〜12月プルダウン)。GET側は select('*') で返る。 | app.py + ledger.html |
| ledger-monthly-balance-api-v1 / -ui-v1 | 月初残高をlocalStorage→DB化、事業部別。`GET/POST /api/ledger/monthly_balance`。月初残高モーダルに事業部プルダウン。getInitBalanceはキャッシュ(_monthlyBalanceCache)から返す同期関数化、loadSubLedgerで_prefetchMonthlyBalance事前取得(全事業=合計/特定事業部=その額)。 | app.py + ledger.html |
| ledger-opening-balance-api-v1 / -ui-v1 | 期初残高の設定UI・API(事業部別手入力)。ヘルパー `_ledger_fiscal_period_start(f_code, ref_date)` が決算月から期初日算出(10月決算なら2025-11-01)。`GET/POST /api/ledger/opening_balance`。設定画面に決算期ラベル+事業部別入力欄。 | app.py + ledger.html |
| ledger-cumulative-cashfill-v1 | **本丸**。`_ledger_recalc_day_inner` を「その日だけ」→「決算期内を期初残高起点で累積」に作り変え。target_dateの決算期開始日を求め、期初〜min(期末,今日)のauto_fill/transferを全削除→補填元以外の各事業部について期初残高起点で日付順累積し不足日に補填の対を立てる。補填元未設定時は旧フォールバック(事業主借・単日)維持。 | app.py |
| ledger-opening-autorecalc-v1 | 期初残高を保存したら、その決算期の累積補填を自動再計算(api_ledger_opening_balance_save 内で `_ledger_recalc_day(supabase, f_code, period_start)` を呼ぶ)。期初残高変更が即座に補填へ反映される。 | app.py |

### 21-5. DEV検証（累積本体）= 完全成功

- 6/9引出1万→6/10経費3千(補填0)→6/11経費8千(**6/11だけ補填1千**) ✓
- **前日(6/8)引出5千を後から追加→6/11補填が自動で見直され消えた** ✓(HIROの当初の悩みが解決)
- 期初残高が起点に効く(期初を変えて保存だけで補填が即再計算) ✓
- 複数事業部(div2/div3)の独立累積、決算期またぎ ✓
- サンドボックスで5シナリオPASS(6/9-6/11例/期初で賄える/複数事業部/引出複数日繰越)

### 21-6. 本番移行（既存補填の立て直し）= 完了

- 本番会計データは**2026年2月開始**(2025-11〜2026-01はデータなし)。決算月10、補填ON、補填元=接骨院(1)。
- 本番の**期初残高を3事業部とも0**で設定(period_start=2025-11-01)。介護は現金収入なく接骨院補填で回す運用のため期初0が実態。
- 立て直し方法: 累積計算は「決算期の頭から通し計算」なので、本番のどこか1日(2026-02-01の手動仕訳)を**無変更で再保存**すれば `_ledger_recalc_day` が走り、**期全体(2月〜今日)が一気に立て直る**。手動仕訳(経費・引出・売上)は不変、変わるのはauto_fillのみ。冪等。
- **シミュレーションと本番結果が完全一致**:
  - 2月: 旧467,265→新251,713(-215,552) ※2/26引出32万・2/27引出3万が2/28経費21.5万を賄い補填減
  - 3月: 旧526,261→新391,813(-134,448) ※2月末引出残が3月へ繰越
  - 4月: 484,170(差0) / 5月: 533,518(差0) / 6月: 473,589(差0) ※月初に大引出なく繰越ほぼ0で日単位と同じ
- 出納帳画面でも残高の流れ(補填入金→経費出金→残高推移)が自然に表示されることを確認。
- **注意**: 旧ロジックの補填には戻せない(コードが新ロジックに置換済み)が、手動仕訳は無傷で、補填は何度でも冪等に再計算可能。新ロジックの方が設計として正しい。

### 21-7. 残タスク（次セッション）

1. **決算確定ボタン**(`ledger_fiscal_closes` 使用): 確定/解除UI、確定済み期への変更は保存時アラート(金額提示)、決算確定時に期末残高を翌期初へ自動コピー。**配置はHIRO検討中**(設定内だと押し忘れ懸念→出納帳上部に通知的に出す案、決算月を過ぎた未確定期があるとバッジ等)。
2. **領収書の削除・編集**(OCR取込画面/保管庫の両方から、仕訳にも反映)。削除時の紐付く仕訳の扱い(残す/消す)は仕様未確定。Claude提案は「領収書のみ削除・仕訳は会計記録として残す」。
3. (継続) §18方針B第2段、§19残課題 など。

### 21-8. コミット（このセッション後半・全て本番反映済み）

```
ledger-fiscal-month-api-v1 / ledger-fiscal-month-ui-v1
ledger-monthly-balance-api-v1 / ledger-monthly-balance-ui-v1
ledger-opening-balance-api-v1 / ledger-opening-balance-ui-v1
ledger-cumulative-cashfill-v1
ledger-opening-autorecalc-v1
```

### 21-9. 申し送り（重要）

- **ブランチ取り違えに注意**: このセッションで2回、本番マージ後に `git checkout tasukaru-dev` で戻し忘れ、本番ブランチ(tasukaru)に直接コミットした。いずれも内容は検証済みで結果オーライ、dev にmergeで揃えて解消。**各作業の前に必ず `git branch --show-current` で `tasukaru-dev` を確認**すること。本番マージ後は即 `git checkout tasukaru-dev`。
- `git checkout` のたびに `M README.md` が出続けている(別件の未コミット変更、今回作業と無関係)。
- DEVに検証ダミーデータ残存(6月の半日型6/9引出1万・6/10経費3千・6/11経費8千、期初残高div2=0等)。実害なし。
- Chrome MCP連携が時々タイムアウト/HTMLエラー返却。本番未デプロイのAPI(例: opening_balance)は404を返す→デプロイ済みか確認。
- 現在のブランチ状態: 本番`tasukaru`・`tasukaru-dev` ともに最新コミット(f04aef6相当)で一致済み。


---

## 22. 現金収入拡大・表示/出力改善・二重登録防止・クレカ明細出力（2026-06-17 セッション）<!-- readme-ledger-session3-2026-06-17 -->

セクション21の続き。HIROが本番で気づいた問題の修正と、要望機能の実装。**すべて本番反映・動作確認済み**。最新コミットは tasukaru/tasukaru-dev ともに `89a85b9` 以降で一致。

### 22-1. 累積補填の現金収入を拡大（重要バグ修正） ledger-cashfill-allin-v1

**症状**: 後から感謝祭の売上(現金受取)を入力したのに、その日の補填が見直されず残った。5/30 感謝祭売上¥129,500(借方=現金/貸方=雑費)があるのに、経費¥116,990に対し補填¥116,990が立ったまま。

**原因**: 累積計算の「現金収入W」の集計が「普通預金引出(借方=現金×貸方=102)」だけに限定されていて、売上の現金受取(借方=現金×貸方=売上/雑費)が繰越残高に算入されていなかった。

**修正**: `_ledger_recalc_day_inner` の by_date 構築で、Wの条件を「借方=現金×貸方=102」→「**借方=現金の手動仕訳すべて**」に拡大。man_entries は auto_fill/transfer 除外済みなので、借方=現金なら引出・売上の現金受取など現金が増える取引すべてが算入される(補填自体は入らない)。**HIRO方針: 「現金として一旦入ったものはすべて補填ルールに基づく」**。

**本番立て直し結果**: 5月の補填合計 133,924→16,934(−116,990)。5/30補填消滅。月末残高12,510(感謝祭の黒字¥12,510=売上129,500−経費116,990が現金として残る=実態通り)。サンドボックス4シナリオ+DEV実機(6/10売上2千追加で6/11補填消滅)で検証。

### 22-2. 仕訳帳の振替表示を直感化 ledger-journal-transfer-display-v1

**症状**: 仕訳帳で資金移動(現金↔普通預金)が「現金 → 普通預金 −¥350,000」と費用同様の赤字マイナスで出て直感に反する。普通預金引出(借方現金/貸方102)なのに矢印が逆に見える。

**修正(renderEntries)**: 収益/費用/振替の3分岐表示に。
- 収益(貸方=収益科目): +緑、矢印 借方→貸方(維持)
- 費用(借方=費用科目): −赤、矢印 借方→貸方(維持)
- **振替(損益に無関係)**: 符号なし・中立色グレー(.entry-amount.transfer)+「振替」バッジ、矢印を「**貸方→借方**」(お金が出た口座→入った口座)。例: 借方現金/貸方102 →「普通預金 → 現金」。
- **画面のみ**。出納帳・税理士提出用出力(CSV/Excel/PDF)は簿記ルールのまま(HIRO方針: 画面=直感的、提出資料=帳簿ルール)。

### 22-3. 出納帳の並び順を画面/Excel/PDFで統一

**症状**: 画面は「同日内 入金→出金」順だが、Excel/PDF出力は並べ替えされず順序が食い違い、PDFでは残高が一時マイナスになっていた(出金が先)。

**修正**:
- `ledger-subledger-sort-export-v1`(ledger.html): 画面の並べ替えを共通関数 `_sortSubLedgerEntries(type, entries, cfg)` に切り出し、renderSubLedger と exportSubLedgerExcel の両方から呼ぶ。
- `ledger-subledger-pdf-layout-v1`(app.py, api_ledger_subledger_pdf): PDFも「日付→入金(借方=対象科目)優先」で並べ替え。残高がマイナスにならない。

### 22-4. PDF出納帳のレイアウト改善 ledger-subledger-pdf-layout-v1

**症状**: 事業部「半日型デイサービス」や相手科目が列幅不足で1文字ずつ縦書き折り返し。

**修正(api_ledger_subledger_pdf)**:
- 事業部で絞っている場合(div_filter が特定事業部)は**事業部列を省き、ヘッダーに「事業部: ○○」を表示**。全事業(all)のときは事業部列を残す(show_div_col)。
- **A4横向き**(@page size:A4 landscape)+colgroupで列幅明示+table-layout:fixed+nowrap指定で折り返し抑制。

### 22-5. 仕訳の二重登録防止 ledger-save-guard-v1

**症状**: 仕訳保存時にレスポンスが遅く2度押し→2件登録されることがある。

**修正(saveEntry, ledger.html)**:
- 保存ボタンに id="entry-save-btn"。CSSに .btn-spinner(回転アニメ)+.ledger-btn:disabled。
- 多重実行ガード `_saveEntryInProgress` フラグ。押下直後にボタン無効化+「(スピナー)保存中...」表示。try/finally で成功・失敗・例外いずれもボタン確実復帰。
- DEV/本番で表示動作確認済み(保存中はdisabled+opacity0.7+スピナー回転)。

### 22-6. クレカ明細のCSV/PDF出力（新機能） ledger-orico-export-v1 / ledger-orico-pdf-v1

クレカ明細タブ(pane-orico)に「CSV出力」「PDF保存」ボタンを追加。現在のフィルタ(all/unlinked/linked)を尊重。

- **CSV**(ledger.html, フロント完結): UTF-8 BOM付き(Excel文字化け防止)。列=支払日/利用日/利用先/金額/勘定科目/Amazon商品名。科目名は ACCOUNTS から id→name 解決。Amazon商品名は amazon_detail(JSON)の items を「/」結合 or summary。`exportOricoCsv()`。
- **PDF**(app.py, サーバー生成 `/api/ledger/orico_pdf`): 支払日セクション×明細表(利用日/利用先/金額/勘定科目/Amazon商品名)。A4横+colgroup+table-layout:fixed。`exportOricoPdf()` が `window.open('/api/ledger/orico_pdf?filter=...')`。
- **クレカ明細モード(is_credit_csv_enabled)有効な施設のみ**。本番(cocokaraplus-5526)で実データ出力・印刷確認済み。
- **修正 ledger-orico-pdf-fix-v1**: orico_pdf で make_response/quote が未定義(NameError)だったので、subledger_pdf 同様に関数内ローカルインポート `from flask import make_response` / `from urllib.parse import quote` を追加。

### 22-7. 未解決・申し送り

- **役員報酬の会計処理(最重要・PENDING)**: HIROの役員報酬は計上のみで未払い分がある(妻=岸本朋子の給与は実払い済み)。「現金で支払い済み」と記録するため帳簿上も実際も現金が残る(本番半日型の月末残高が0にならない正体)。**累積補填ロジックは正確で、実態を正しく反映している(バグではない)**。金額の記載方法(減額/未払計上)・融資への影響は**顧問税理士マター**。Claudeは判断不可、決まった方針のシステム反映のみ担当。
- **PDFビューアのダウンロードボタンが効かない件**: ブラウザ/OS標準のPDFビューアの機能で、TASUKARU側では制御不可。印刷からのPDF保存は可能。対処するなら「PDF保存の動作をビューア表示→直接ダウンロードに変更」だが優先度低。
- **ブランチ取り違え多発(教訓・重要)**: このセッションで本番マージ後に `git checkout tasukaru-dev` で戻し忘れ、本番ブランチ(tasukaru)へ直接コミットが**4回**発生。毎回 dev に merge で揃えて解消(内容は検証済み)。**対策: 本番作業は「checkout tasukaru → merge → push →(デプロイ)→ checkout tasukaru-dev」で1セット。最後の checkout tasukaru-dev まで打って完了とする。各作業前に必ず `git branch --show-current` 確認。**
- `git checkout` のたびに `M README.md` が出続けている(別件の未コミット変更、無関係)。

### 22-8. 次セッションの残タスク

1. **決算確定ボタン**(`ledger_fiscal_closes` 使用、§21-7参照): 確定/解除UI、確定済み期への変更は保存時アラート、決算確定時に期末残高を翌期初へ自動コピー。配置はHIRO検討中(設定内だと押し忘れ→出納帳上部に通知的に出す案、決算月超過の未確定期にバッジ)。
2. **領収書の削除・編集**(OCR取込画面/保管庫の両方から、仕訳にも反映)。削除時の紐付く仕訳の扱い未確定。Claude提案: 領収書のみ削除・仕訳は会計記録として残す。
3. **役員報酬の会計処理**(税理士相談後にシステム反映)。
4. (継続) §18方針B第2段、§19残課題。

### 22-9. このセッションのコミット(全て本番反映済み)

```
ledger-journal-transfer-display-v1   (仕訳帳 振替表示)
ledger-subledger-sort-export-v1      (Excel並び順 共通化)
ledger-subledger-pdf-layout-v1       (PDF 並び順+レイアウト)
ledger-cashfill-allin-v1             (現金収入拡大)
ledger-save-guard-v1                 (二重登録防止)
ledger-orico-export-v1               (クレカ明細CSV)
ledger-orico-pdf-v1 / -fix-v1        (クレカ明細PDF)
```


---

## 23. 決算確定機能・領収書削除（2026-06-17 セッション後半）<!-- readme-ledger-session4-2026-06-17b -->

セクション22の続き。§22-8 残タスクの 1(決算確定ボタン)と 2(領収書の削除)を実装。**DEV検証済み・本番反映済み**。

### 23-0. DDL: ledger_fiscal_closes を新設計で作り直し（重要）

§21-7 で計画した旧テーブルが DEV/本番ともに残存していた。旧構造は `id/facility_code/period_end/is_closed/closed_at/released_at` で、**新コードが要求する `period_start`/`closed_by`/`closing_balances` が無かった**。`CREATE TABLE IF NOT EXISTS` が既存テーブルを見てスキップするため `column period_start does not exist (42703)` エラーが発生。

**対処**: 両プロジェクトとも0件だったので DROP+CREATE で作り直した。**DEV→本番の順で個別適用**。

```sql
DROP TABLE IF EXISTS ledger_fiscal_closes;
CREATE TABLE ledger_fiscal_closes (
    id BIGSERIAL PRIMARY KEY,
    facility_code TEXT NOT NULL,
    period_start DATE NOT NULL,      -- 期初日 例 2025-11-01
    period_end   DATE NOT NULL,      -- 期末日 例 2026-10-31
    is_closed BOOLEAN NOT NULL DEFAULT TRUE,
    closed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_by TEXT,
    closing_balances JSONB,          -- 確定時の事業部別期末残高スナップショット {div: amount}
    UNIQUE (facility_code, period_start)
);
```

教訓: 過去に計画だけして空テーブルを作っていた場合、`IF NOT EXISTS` は構造の食い違いを検出しない。新機能のDDL適用前に既存テーブルの列を必ず確認する。

### 23-1. 決算確定機能 ledger-fiscal-close-v1（app.py）

**ヘルパー**:
- `_ledger_period_bounds(f_code, period_start_iso, ref_date)`: 期初iso(or今日基準)から (期初, 期末) を返す。
- `_ledger_period_end_balances(supabase, f_code, period_start_iso)`: **事業部別 期末現金残高**を `{div(str): amount}` で算出。期初残高 + 期間内の全仕訳(auto_fill/transfer含む)の現金増減(借方現金=+/貸方現金=−)。補填ロジックを再現せず、確定済み帳簿実態をそのまま積算する方式(最も正確)。
- `_ledger_is_period_closed(supabase, f_code, entry_date)`: entry_date が確定済み期に属するか。ガード共通判定。例外時は安全側でFalse。

**API**:
- `GET /api/ledger/fiscal_close`: 当期含む過去6期を列挙し確定状態を返す。`is_current`/`overdue`(決算月超過の未確定)フラグ付き。
- `POST /api/ledger/fiscal_close`: 確定。期末残高を算出→`ledger_fiscal_closes`にupsert(スナップショット保存)→**翌期初(=期末日翌日)の`ledger_opening_balances`へ事業部別に上書きコピー**→翌期が当期なら累積補填を再計算。
- `POST /api/ledger/fiscal_close/cancel`: 解除(is_closed=false)。翌期初残高は変更しない。

### 23-2. 確定済み期のガード ledger-fiscal-close-guard-v1（app.py）

確定済み期への変更を **409 + `code:'fiscal_closed'`** でブロック(HIRO方針: 警告ブロック、解除で再編集可)。挿入箇所4つ:
- `api_ledger_entry_save`: 新規は entry_date、編集は対象idの現行日付も判定。
- `api_ledger_entry_delete`: 削除前の日付で判定。
- `api_ledger_transfer`: 事業間移動の entry_date で判定。

**未対応(意図的)**: CSV取込・クレカ明細取込は今回ガード対象外(取込は期末後に走るケースが稀、形式ごとの日付判定が必要なため)。必要になれば次回追加。

### 23-3. 領収書削除 ledger-receipt-delete-v1（app.py）/ -ui-v1（ledger.html）

**HIRO方針: 領収書(receipts行)のみ削除。紐付く仕訳(journal_entries)は会計記録として残す。**
- `DELETE /api/ledger/receipt/<int:receipt_id>`: receipts行を削除。entry_id があれば `kept_entry:true` を返し「仕訳は残した」旨をメッセージに付加。仕訳側は一切触らない。画像のStorage物理削除はしない(孤立しても帳簿無害・将来別タスク)。
- 保管庫(renderReceiptVault)の各カードに「🗑️ 領収書を削除」ボタン。`deleteReceiptFromVault(id, isJournaled)`: 仕訳済みなら確認ダイアログで「紐付く仕訳は会計記録として残ります」と明示→DELETE→loadReceiptVault再読込。

### 23-4. DEV検証結果（すべてPASS）

- 期一覧: 当期(2025-11〜2026-10)=is_current、過去5期=overdue を正しく判定。決算月10月設定が反映。
- 確定→確定状態記録(closed_by/closed_at)、overdue解消。
- **期末残高コピー(中身あり)**: 当期確定で事業部1=¥52,015/事業部2=¥1,000/事業部3=¥0 を算出し翌期初(2026-11-01)へ反映。即解除も成功。
- ガード: 確定済み期(2025-03-15)への仕訳保存が 409 fiscal_closed でブロック。解除後は保存可(検証データは即削除)。
- 領収書削除: 未仕訳id=4を削除→6件→5件、kept_entry:false 正常。

### 23-5. 申し送り

- DEV検証時、当期確定検証で **翌期初(2026-11-01)の`ledger_opening_balances`にレコードが残存**(事業部1=¥52,015等)。次々期の話で実害は薄く、実態に近い値なので残置可。消すなら `DELETE FROM ledger_opening_balances WHERE facility_code='DEMO001' AND period_start='2026-11-01';`。
- 本番(cocokaraplus-5526)では決算確定カードの表示確認のみ。**確定操作は実際の決算判断のため HIRO のタイミングで実行**(顧問税理士との整合確認後を推奨)。
- 役員報酬の会計処理(§22-7・§22-8): 引き続き税理士マター・PENDING。

### 23-6. 残タスク

1. **役員報酬の会計処理**(税理士相談後にシステム反映)。
2. (任意)CSV/クレカ取込の確定済み期ガード。
3. (任意)領収書編集機能(OCR結果の修正・仕訳側との同期)。今回は削除のみ実装。
4. (継続) §18方針B第2段、§19残課題。

### 23-7. このセッションのコミット(本番反映済み)

```
ledger-fiscal-close-v1        (決算確定 API・ヘルパー)
ledger-fiscal-close-guard-v1  (確定済み期ガード ×4経路)
ledger-receipt-delete-v1      (領収書削除 API)
ledger-fiscal-close-ui-v1     (決算確定 UI)
ledger-receipt-delete-ui-v1   (保管庫 削除ボタン)
DDL: ledger_fiscal_closes 作り直し(DEV/本番)
```


## 24. 連絡帳機能（フェーズ1〜AI家族文生成・バイタル測定回マージ）（2026-06-18 セッション）<!-- readme-renraku-session-2026-06-18 -->

デイの「連絡帳」（その日の利用者の様子をご家族に伝えるノート）をゼロから実装し、
DEV→本番へ反映済み。バイタル表示・表示項目トグル（個別/施設既定）・機能訓練詳細・
行った場所・ご家族メッセージのAI生成・測定回マージまでを含む。

### 24-1. データモデル（DDL: DEV/本番とも適用済み）

```sql
-- 連絡帳本体（利用者×日付で1件、items は柔軟な jsonb）
renraku_notes(
  id BIGSERIAL PK, facility_code TEXT, patient_id TEXT, note_date DATE,
  items JSONB, special_note TEXT, family_message TEXT, next_visit TEXT,
  staff_name TEXT, created_at, updated_at,
  UNIQUE(facility_code, patient_id, note_date))

-- 施設既定の表示項目（一括設定）
renraku_settings(
  facility_code TEXT PK, visible JSONB, updated_at)

-- 利用者ごとの表示項目（個別設定。次回も引き継ぐ）
renraku_patient_settings(
  id BIGSERIAL PK, facility_code TEXT, patient_id TEXT, visible JSONB, updated_at,
  UNIQUE(facility_code, patient_id))
```

- `items`(jsonb) の主なキー: meal_main/meal_side/water/bath/toilet/training（チップ選択値）、
  pickup/dropoff（送迎）、rec（レク）、training_details（機能訓練の配列）、places（行った場所の配列）。
- `visible`(jsonb): 各項目キー→true/false。キーが無い項目は表示(true)扱い。
  施設既定には `_ai_family`（家族向けAI生成のON/OFF, 既定OFF）も格納。

### 24-2. API（app.py, marker別）

- `renraku-v1`:
  - `GET /renraku` ページ、`GET /api/renraku/list?date=`（その日バイタルがある利用者一覧）、
    `GET /api/renraku/get?patient_id=&date=`（単一利用者＋その日の全バイタル時刻順＋note）、
    `POST /api/renraku/save`（note を upsert）。
  - 利用者の突合は `patient_profiles.id`(UUID) = vitals.patient_id。
- `renraku-settings-v1`:
  - `GET/POST /api/renraku/settings`（施設既定 visible）、
    `GET/POST /api/renraku/patient_settings`（利用者ごと visible）。
  - `/api/renraku/get` のレスポンスに `visible`(適用後) と `visible_source`('patient'|'facility'|'default')
    を追加。優先順位は 個別→施設既定→全表示。
- `renraku-ai-family-v1`:
  - `POST /api/renraku/generate_family`（patient_id, date）。
    その利用者・その日の `records`（ケース記録）を読み、Gemini でご家族向けの文章に変換して返す。
    AI統合記録(staff_name='AI統合記録')があれば優先、なければ通常記録を結合。
    プロンプト RENRAKU_FAMILY_PROMPT で「介護職員がご家族へ報告する丁寧な口調／他利用者名は出さない／
    記録にない事実は創作しない(ハルシネーション禁止)」を厳守。記録が無ければ生成せず案内を返す。
    生成結果は連絡帳の「ご家族へのメッセージ」欄に挿入し、その後は手で編集可能。

### 24-3. UI（renraku.html, marker別の進化）

- `nav-renraku-v1`(base.html): ボトムナビに「連絡帳」を追加。
- `renraku-ui-v2`: 各項目を「ヘッダ(ラベル＋トグル, 常時表示)＋ボディ(入力欄, 非表示対象)」の
  2段構成に変更。**トグルをオフにしてもトグル自体は残り、再表示できる**（旧実装のバグ根治）。
  バイタル測定が2回以上のときのみ折れ線グラフを描画、1回のみは一覧表だけ（点だけ防止）。
  機能訓練「実施/一部」で訓練名・時間(分)・メモを複数行追加/削除（items.training_details 配列）。
- `renraku-savebar-navh-v1`: 「連絡帳を保存」バーをボトムナビ実測高さに固定
  （`bottom: var(--rk-nav-h)`、JSで `.bottom-nav` の高さ=実測137pxを取得）。固定値だと端末差でずれるため。
- `renraku-ui-v3`:
  - 機能訓練の時間入力の右に「分」単位表示。
  - レク・活動の下に「行った場所」欄（無限追加・削除・トグル付き, items.places 配列）。
  - 「ご家族へのメッセージ」に「AIで下書き生成」ボタン（施設設定 `_ai_family` がONのときのみ表示）。
  - 一括設定モーダルの下端をボトムナビの上で止める（隠れる不具合の修正）＋AI生成のON/OFFトグルを追加。
- `renraku-vital-merge-v1`:
  - **連絡帳バイタルを「同じ測定回(=10分以内)」単位にまとめて表示**（rkMergeVitals）。
    本体バイタルは体温と血圧脈拍が別レコードになり得る（同一測定でも別行）。それらは10分以内に
    登録されているため「同じ回」とみなし、measured_at 昇順で直前と10分以内なら統合。
    各項目は空でない値を採用（複数あれば後=新しい measured_at を優先）、代表時刻は回の先頭。
    → 同時刻が2列に割れる/点だけグラフになる不具合を解消。マージ後1回ならグラフ非表示・一覧のみ。

### 24-4. 重要な実装メモ

- 連絡帳の利用者一覧は「その日のバイタルがある人」を対象にしている。
- ご家族メッセージのAI生成は**既定OFF**。本番で使うには施設の「表示項目の一括設定」で
  「ご家族向けメッセージのAI生成を使う」をONにする必要がある。
- vitals は本体が測定ごとに INSERT（同日も別レコード, measured_at で区別）。
  本番には1日に2〜8レコードの利用者が複数おり、これが §24-3 のマージ対象。
- 表示項目トグルは個別設定が即保存され、その利用者の次回以降にも引き継がれる。

### 24-5. このセッションのコミット（DEV→本番 反映済み）

```
renraku-v1                  (連絡帳ページ・list/get/save API)
nav-renraku-v1              (ボトムナビに連絡帳)
renraku-settings-v1         (表示項目: 施設既定/利用者ごと API＋get に visible)
renraku-ai-family-v1        (ご家族メッセージ AI生成 API)
renraku-ui-v2               (トグル常時表示・1回時グラフ無し・機能訓練詳細)
renraku-savebar-navh-v1     (保存バーをボトムナビ実測高さに固定)
renraku-ui-v3               (分単位・行った場所・AI生成ボタン・モーダルかぶり修正)
renraku-vital-merge-v1      (バイタル 同じ測定回=10分以内 をまとめて表示)
DDL: renraku_notes / renraku_settings / renraku_patient_settings (DEV/本番)
```

### 24-6. 連絡帳の残課題（次セッション候補）

- 連絡帳の印刷（フェーズ2）・LINE送信（フェーズ3）は未実装（LINE連携自体が未実装）。
- 本番デプロイ後の総点検（非破壊チェック）の最終確認。









## 25. 連絡帳印刷（フェーズ2）完成・モニタリンググラフ修正・LINE連携の土台（2026-06-22 セッション）<!-- readme-print-line-session-2026-06-22 -->

### 25-1. モニタリング報告書グラフの歪み・凡例修正（本番反映済み d8dc2e9）

`templates/print_preview.html` のフィットネスmini-chart（体重/握力/TUG/CS-30/5m歩行/片脚立位）が縦横に歪む問題と、canvas内凡例が線に重なる問題を解消。

- **真因**: canvas が CSS で固定高さ＋`maintainAspectRatio:false` のため、Chart.js のバッファ比率と表示ボックス比率が不一致。さらに描画経路が2系統あった。
  - 2系列（grip/walk/balance）→ `drawBalanceChart` 経由
  - 1系列（weight/tug/cs30）→ `makeChartConfig` + `new Chart` 経由（こちらは options に aspectRatio 指定が無く Chart.js デフォルト=2 で横伸び）
- **解法**: 生成時に `maintainAspectRatio:true` + `aspectRatio`（canvas実寸比 w/h）を指定し、**生成直後に同期で `chart.options.aspectRatio=ar; chart.resize();`** を呼ぶ。初期options指定だけでは固定高さに負けるため、生成後の同期resizeが決め手。
- **凡例**: canvas内凡例（Chart.js legend）をやめ、canvas直後にHTML凡例（実線/破線サンプル＋「右(実線)/左(破線)」等）を配置。極小サイズでも線と重ならず歪まない。
- **教訓**: 歪みは描画経路ごとに対処が要る。グラフ修正は「全描画経路を最初に洗い出してから」着手すべき（経路特定を後回しにして遠回りした）。
- マーカー: `chart-aspect-fix-v3`(c14b569) / `chart-aspect-fix-v4`(42df6f4) / `chart-aspect-fix-v5`(ba32331) / `legend-html-v1`(b07e0e2、template=1) / `tmpl4-chart-v1`(d8dc2e9、template=4)
- 補足: 「1 / 1」表示は `.page-number`（@media print で `display:none !important`、画面のみ表示）の仕様。連絡帳画面のバイタルSVGは手書きSVGのため歪み問題なし。

### 25-2. 連絡帳の印刷（フェーズ2）完成（本番反映済み 0f0159c）

仕様: 1利用者・1日・1枚、一枚ずつ／まとめて連続印刷、表示項目は既存visible設定（個別→施設→全表示）を流用、ご家族メッセージはAI生成文を印刷前に編集可、バイタルは表＋SVGグラフ（2回以上測定時）、縦/横選択可。

- **ルート**: `app.py` に `/renraku/print?date=&ids=`（カンマ区切りで複数patient_id）。各idの renraku_notes / vitals / profile / visible を集約し JSON 埋め込みでテンプレに渡す。マーカー `renraku-print-route-v1`(889280e)。
- **テンプレ**: `templates/renraku_print.html`（新規）。サーバーから `RK_PRINT_DATA` を受け取り JS で各利用者カードを描画。buildVitals（連絡帳画面のSVGロジック移植・Chart.js不使用）/ buildItems（RK_DYN_FIELDS: transport/meal_main/meal_side/water/bath/toilet/training/rec/places + special_note/family_message/next_visit）/ buildPage。家族メッセージは `contenteditable`。@media print でツールバー非表示。
- **縦横切替**: 縦=1カラム、横=当初2カラム→最終的に1カラム縦積みに変更（`rkpSetOrient` で `@page size` を動的style要素で切替）。マーカー `renraku-print-orient-v1`(2bf67ae) / `renraku-print-layout-v2`(a803a13、バイタル上部全幅) / `renraku-print-layout-v3`(711d7fe、横=1カラム縦積み・バイタル表 width:auto左揃え)。
- **微調整**: バイタル値セル min-width:72px（項目名列除く）、氏名行は氏名＋様のみ（No./介護度削除）、バイタル表ベース幅 width:auto（縦横とも左揃え自然幅）。マーカー `renraku-print-tweak-v4`(4d0b27d) / `renraku-print-tweak-v5`(ec1c59e)。タイトルは「連絡帳」（当初ひらがな誤記を修正 51e84a5）。コメント内 `{{ ... }}` のJinja誤解釈バグ修正(469f539)。
- **導線**: `templates/renraku.html` に印刷ボタン。詳細=「印刷」(rkPrintOne→その利用者1枚)、一覧=「まとめて印刷」(rkPrintAll→`RK_LIST` のうち `noted`(記入済み)のみカンマ連結、0件ならalert)。`rkLoadList` で `RK_LIST` 保持。マーカー `renraku-print-link-v1`(0f0159c)。

### 25-3. プロンプトのトーン調整・本人認識強化（本番反映済み e7c78e4）

連絡帳AI家族文とモニタリング報告書の生成を、硬すぎる敬語（二重敬語）からトーンB（やさしいです・ます、過剰敬語回避）に統一。利用者本人名を明示し、他利用者は「他の利用者様」と伏字化（先月モニタリングで本人認識できず変な文章になった不具合の対処）。app.py の RENRAKU_FAMILY_PROMPT / api_generate_monitoring の BASE_PROMPT / _auto_generate_monitoring の BASE_PROMPT の3箇所。マーカー `prompt-tone-v1`。

### 25-4. LINE連携の土台（DEVのみ・本番未反映）<!-- readme-line-foundation -->

**方針: 施設別トークン方式（SaaS対応）**。全施設共通1アカウントではなく、施設ごとに自前のLINE公式アカウント・自前トークンを使う。データもアカウントも施設ごとに完全分断。家族から見れば「いつものその施設のLINE」から連絡帳が届く。

- **DDL（DEVのSupabaseに適用済み）**: `line_settings`（facility_code text PK / channel_access_token_enc text / channel_secret_enc text / line_oa_name text / enabled boolean default false / created_at / updated_at）。トークン・シークレットは Fernet 暗号化して `_enc` カラムに保存。
- **暗号化**: `cryptography` の Fernet（supabase の依存で既にインストール済み、requirements.txt 追加不要）。マスター鍵は環境変数 `LINE_TOKEN_ENC_KEY`（**DEVと本番で別々の鍵**にする方針＝各環境で暗号化し直す）。
- **app.py ヘルパ（マーカー `line-crypto-v1`、856a66c）**: `_line_get_fernet()` / `_line_encrypt(plain)` / `_line_decrypt(enc)` / `get_line_settings(supabase, f_code)`（復号済み設定を返す。`has_token`/`has_secret` フラグ付き）/ `save_line_settings(...)`（暗号化upsert、token/secret空なら既存値温存）。
- **テスト用アカウント**: スタッフ用公式LINE「【公式】ココプラスタッフ用」(@145tminp)で Messaging API 有効化（Channel ID **2010464312**、プロバイダー TASUKARU）。本番の家族とつながっている公式LINEとは別アカウント。本番アカウントは開発完成後に同様に有効化して本番 line_settings に登録する。
- **DEV環境変数（GCPコンソールから設定済み）**: `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_CHANNEL_SECRET`(2b6e7…) / `LINE_TOKEN_ENC_KEY`。※前者2つは開発初期の動作確認用。最終的にトークンはDB（line_settings）へ移行し環境変数からは削除予定。`LINE_TOKEN_ENC_KEY` は残す。
- **セキュリティ方針**: トークンは平文表示しない（設定画面はマスク表示・登録/更新のみ）、保存は暗号化、登録は施設管理者限定、Cloud Run はHTTPS。トークンはターミナル履歴を避けGCPコンソール画面から入力。

### 25-5. LINE連携の次タスク（次セッション）<!-- readme-line-todo -->

実装順（おすすめ）:
1. **施設のLINE設定画面**（管理者限定・トークンはマスク表示・`save_line_settings` を呼ぶ保存API）。
2. **Webhook**（公開エンドポイント `/line/webhook`。署名検証に `get_line_settings` の `channel_secret` を使用。どの施設宛てかの判別が必要）。
3. **友だちのuserId受信と未紐付けリスト**（友だち追加 or メッセージ受信で userId 取得。Webhook 設定前に追加済みの人は一度メッセージを送ってもらう必要あり）。
4. **家族↔利用者の紐付け**（合言葉=利用者ごとの招待コードで自動紐付け ＋ 管理画面で手動紐付け の併用。誤紐付けは事故になるため慎重に）。
5. **連絡帳のLINE向け整形**（行った場所・食事量を箇条書き、連絡事項は家族向け文章、血圧グラフは**画像(PNG)**で送る ※LINEは公式アカウントからのPDFファイル送信に非対応）。
6. **送信プレビュー編集UI** → **送信API**（プッシュメッセージ。1回最大3吹き出し＝1通。料金は通数=送信回数×友だち数）。

注意点メモ:
- LINE公式アカウントの応答モードは「チャット」のまま Webhook 有効化で手動チャットとAPI送信を共存可能（本番アカウントは日常的に手動チャット運用中のため要配慮）。
- 料金: コミュニケーション(0円/月200通)・ライト(5,000円/月5,000通)・スタンダード(15,000円)。プッシュ/マルチキャスト/ブロードキャストが課金対象、リプライは対象外。


## 26. LINE連携設定UI追加・起動時NameError修正（2026-06-22 セッション）<!-- readme-s26-line-ui-fix -->

### 26-1. LINE連携設定画面のUI追加（DEV・マーカー `line-settings-ui-v1`）

`templates/admin.html` の「AIカテゴリ自動振り分け」section-box の直前に「LINE連携設定」section-box を追加。

- **入力項目**: 公式アカウント名 / チャネルアクセストークン / チャネルシークレット / 有効トグル / 保存ボタン。
- **マスク表示**: トークン・シークレットは `type=password`。プレースホルダーは登録状況に応じて「登録済み。変更時のみ入力」/「未登録」を出し分け。値そのものは画面に表示しない。
- **JS**: 最後の `</script>` 手前に `loadLineSettings()`（`DOMContentLoaded` で GET `/api/line/settings` を叩きマスク反映）と `saveLineSettings()`（POST。空の token/secret は送らず既存値温存）を追加。
- 検証済み（Chrome MCP）: `#line-settings-box` 表示、GET API が `status:success` でマスク情報のみ返却。

### 26-2. 起動時 `NameError: name 'login_required' is not defined` 修正（マーカー `line-api-move-v1`、c36fa96）

- **現象**: 上記UI追加の push で DEV が再起動した際、全パスが **503 Service Unavailable**。gunicorn worker が import 時にクラッシュ。
- **真因**: 前セッションで追加した LINE設定API（`/api/line/settings` GET/POST、`@login_required` 使用）が app.py の **139行付近**にあり、`login_required` の def（**222行付近**）より**前**だった。import時にデコレータを評価して未定義で落ちた。（`py_compile` は構文チェックのみで import時の NameError は検出しないためローカルでは気づけなかった）
- **対処**: LINE設定APIの2ルートを `login_required` 定義の**直後**へ移動。ヘルパ（`_line_*` / `get_line_settings` / `save_line_settings`）はデコレータ未使用なので移動不要・そのまま。
- **検証**: Cloud Build は成功していたが起動失敗→ログで `NameError` を特定。修正 push 後は `/login` が200、`/admin` 正常表示を確認。
- **教訓**: **デコレータを使うルート/関数は、そのデコレータ定義より後ろに置く。** ファイル前方（import直後の領域）に `@login_required` 付きルートを追加すると起動時に落ちる。今後 LINE 関連のルートは `line-api-move-v1` ブロック（login_required定義後）付近に追加すること。

## 27. LINE連携：Webhook実機疎通・display_name取得・友だち紐付け完成（2026-06-22）<!-- readme-s27-line-friends -->

LINE連携の受信側（Webhook〜家族紐付け）をDEVで完成させ、実機（@145tminp）で確認。全てDEV止まり、本番未反映。

- **DDL（DEV適用済）**: `line_friends`（id uuid PK / facility_code / line_user_id / display_name / patient_id（null=未紐付）/ status default 'unlinked' / linked_by / created_at / updated_at / unique(facility_code,line_user_id)）+ index idx_line_friends_fac。
- **Webhook（`line-webhook-v1`、e8c6c32）**: `POST /line/webhook/<facility_code>`。施設判別=URLのfacility_code。署名検証=get_line_settingsの復号secretでHMAC-SHA256(生ボディ)。follow/messageでuserIdをunlinked保存。
- **旧webhook衝突解消（`line-webhook-legacy-rename-v1`）**: 旧line_webhook()とview関数名衝突で起動失敗→旧をline_webhook_legacyにリネーム。**教訓**: py_compileではendpoint名衝突を検出できない。push前に `SECRET_KEY=dummy python3 -c "import app"` でimport確認。
- **display_name取得（`line-profile-v1`、3fba279）**: _line_get_profile()、タイムアウト3秒・失敗時None。実機でdisplay_name取得確認。
- **友だち管理（`line-friends-api-v1`/`line-friends-ui-v1`）**: 【設計方針：手動紐付けを主軸、合言葉は当面見送り】。誤送信=個人情報漏洩のため必ず人の確認を介す。API 3本(管理者限定・二条件guard・利用者存在検証): GET /api/line/friends, POST .../link, POST .../unlink。UI=admin.html「LINE友だち管理」box、検索窓+確認ダイアログ+解除。実機で青木利夫(5c0f9541-)に紐付け確認。

### 27-送信側の絶対ルール<!-- readme-line-send-rule -->
**linked の友だちにしか送信しない。** unlinked には絶対送信しない。

## 28. 連絡帳をLINEで家族に送信（テキスト・第一段階）完成（2026-06-23）<!-- readme-s28-line-send -->

連絡帳をLINEでご家族に送る機能（テキスト）をDEVで完成し、実機送信成功。全てDEV止まり。

### 28-1. 送信API（マーカー `renraku-line-send-v1`）
- `_line_push(token, to, messages)`: 施設トークンでpush。1回最大3吹き出し(messages[:3])。旧get_line_headers(env単一トークン)は使わず施設別方式。
- `_renraku_to_line_text(note, vitals, name)`: 行った場所・食事・入浴・排泄・機能訓練・特記・家族メッセージを箇条書き、バイタルは数値テキスト(複数回は1行ずつ)。renraku_print と同じ取得パターン(renraku_notes + vitalsをmeasured_dateで絞る)。
- `POST /api/renraku/line_preview`（整形文+linked宛先を返す、送らない）/ `POST /api/renraku/line_send`（確定文をlinkedの全userIdへpush）。**安全: linkedのみ・enabled+token必須**。

### 28-2. 送信UI（マーカー `renraku-line-ui-v1`）
連絡帳詳細の保存バーに「LINEで送る」ボタン。プレビューモーダル（宛先明示・編集可テキストエリア・送信前confirm・二重送信防止）。

### 28-3. UI仕上げ（ボトムナビ・保存バーの可変幅統一）
- 保存バー2段化（`renraku-savebar-actions-v1`）上=保存/下=印刷・LINEで送る。ヘッダに置くとボトムナビに隠れるため移動。
- LINE送信モーダルのナビ回避（`renraku-line-modal-fix-v1`）: max-height:calc(88vh - --rk-nav-h) + margin-bottom:--rk-nav-h。
- **ボトムナビ・保存バーを `--page-max-width` 連動（`bottomnav-width-var-v1`/`renraku-savebar-var-v1`）**: 本文(.page-wrapper)は --page-max-width(初期480px)で幅制御、PCはリサイズハンドル(page-resize-handle)で可変。ナビ(base.html全ページ共通)と保存バーも max-width:var(--page-max-width) にして本文幅に追従。本文・ナビ・保存バーが同幅で揃う。

### 28-4. 次タスク（写真送信）<!-- readme-line-photo-todo -->
1. **連絡帳への写真添付（第二段階）**: renraku_notes に画像URL配列カラム追加(DDL)。UIでアップロード。utils.upload_images_to_supabase(supabase, [photo], f_code) を流用(case-photosバケット、get_public_urlで公開URLを返す)。
2. **写真をLINE送信（第三段階）**: imageMessage(originalContentUrl/previewImageUrlに公開https URL)。1通3吹き出し制限に注意。**要確認: case-photosバケットが公開(public)設定か**(非公開だとLINEが画像取得不可)。
3. （任意）バイタルグラフのPNG送信。現状は数値テキストで十分。

### 28-5. README破損事故と復旧（重要）
patch_readme_s27 系がREADMEを0バイトに破壊する事故が発生。原因はPythonの open(path,'w') が書き込み前にトランケートし、本文中のサロゲート文字(結合絵文字)で UnicodeEncodeError が出て空のまま残ったこと。git(e8c6c32, §26まで138KB)から復元し、§27/§28は `cat >>` で末尾追記する方式で復旧。**教訓: READMEへの追記はPythonで全文書き直さず、追記分のみ cat >> で足す。**

### 28-6. 今セッションのコミット（DEV、tasukaru-dev）
dd8beca 送信API+UI / 02b35e8 保存バー移動 / cb0a608 モーダルナビ回避 / 4f027e1 保存バー480px / 67a31d6 --page-max-width連動。

## 29. カレンダー：繰り返し予定＋先の予定表示バグ修正（2026-06-23）<!-- readme-s29-calendar -->

カレンダーの2つの問題を解消し、繰り返し予定機能を追加。**カレンダー分のみ本番反映済み**（cherry-pick）。LINE関連は本番未反映のまま。

### 29-1. 先の予定が消えるバグ（真因と修正）
- **真因**: calendar.html は初期ロードの `ALL_EVENTS`（calendar_view が埋め込む今月-31日〜+62日のみ）だけを使い、月送り(changeMonth)で新しい月のデータを再取得していなかった。`/api/calendar_events` はサーバーに存在するが**JSから一度も呼ばれていなかった**。約2ヶ月より先の予定は保存されても表示されず「記録されない」ように見えていた。
- **修正（マーカー `calendar-repeat-v1`）**: `__ensureEventsLoaded()` を新設。changeMonth/goToday/switchView 時に表示月の通常イベントを `/api/calendar_events?from=&to=` から取得し ALL_EVENTS にマージ（id重複排除・取得済み月は window.__loadedKeys で記録しスキップ）。これで何ヶ月先でも表示される。

### 29-2. 繰り返し予定（毎日/毎週/毎月/毎年）＝ルール保存方式
- **方式**: 実体展開せず、元イベント1件＋`repeat_type`/`repeat_until` のルールだけ保存（calendar_events に既存カラムあり、DDL追加不要）。表示時に getFilteredEvents が**表示範囲ぶんだけ計算展開**して仮想イベントを生成。レコードが増えず、何年先でも自動表示。月が変われば自動でその月分が出る（毎月・毎年も先まで常に表示される状態が計算で実現）。
- **計算ルール（`__calcRepeatOccurrences`）**: daily=毎日 / weekly=同曜日 / monthly=同じ日(無い月はスキップ) / yearly=同じ月日(2/29は閏年のみ)。元イベント開始日より前は出さない。repeat_until 以降は出さない。仮想イベントは `_virtual:true`/`_srcId` 付き、event_date/end_date を該当日に。
- 繰り返しイベントのクリック→編集/削除は元イベント(ルール)に作用＝繰り返し全体の編集/削除。**個別回の例外は今回スコープ外**（必要になれば例外日記録を後付け）。

### 29-3. 繰り返し日クリックで予定が出ない不具合
- **真因（マーカー `calendar-cellclick-repeat-v1`）**: onCellClick が `ALL_EVENTS`(実レコードのみ)を直接filterし、繰り返し展開分(仮想イベント)を拾えていなかった。月表示(getFilteredEvents使用)には出るがクリックでは出ない不整合。
- **修正**: onCellClick の予定収集を `getFilteredEvents()`(繰り返し展開込み・カレンダーフィルタ内包)ベースに変更。実機(2026年10月の毎週繰り返し)で月表示・クリック両方に表示されることを確認。

### 29-4. 本番反映（カレンダーのみ・cherry-pick）
本番(tasukaru)は §25(0f0159c)で止まっていたため、tasukaru-dev 全体ではなくカレンダー2コミットのみ cherry-pick して本番反映（0f0159c → a5b82b9 → c107a40）。**LINE関連は本番未反映のまま**（本番反映には本番Supabaseへ line_friends DDL適用＋本番Cloud Runへ LINE_TOKEN_ENC_KEY 設定 が前提）。マーカー: calendar-repeat-v1, calendar-cellclick-repeat-v1。

## 30. 連絡帳の写真添付＋写真LINE送信（2026-06-23）<!-- readme-s30-renraku-photo -->

連絡帳に写真を添付（第二段階）し、その写真をLINEで家族に送信（第三段階）まで完成。実機で整形テキスト＋写真6枚の送信成功。全てDEV止まり、本番未反映（LINE一式と同じく本番準備が前提）。

### 30-1. 連絡帳への写真添付（第二段階）
- **DDL（DEV適用済）**: `alter table renraku_notes add column if not exists image_urls jsonb default '[]'::jsonb;`
- **方式A**: 写真は専用APIで即アップロード→公開URL受領、連絡帳保存はJSONのまま image_urls 配列を足すだけ（既存JSON保存を壊さない）。既存ケース記録(records)と同じ case-photos バケット流用（公開・get_public_url）。
- **アップロードAPI（マーカー `renraku-photo-api-v1`）**: `POST /api/renraku/upload_photo`（multipart, @login_required）。`utils.upload_images_to_supabase(supabase, files, f_code)` で case-photos に UUID名アップロード→公開URL配列返却。配置は api_renraku_line_send 末尾の後ろ（login_required定義後）。保存API api_renraku_save の payload に image_urls 追加。
- **UI（マーカー `renraku-photo-ui-v1`）**: 連絡帳詳細の家族メッセージの後ろに「写真」フィールド（表示トグル付き）。「写真を追加」→ `<input type=file accept=image/* multiple>` → 即アップロード→サムネ表示→×削除。状態は RK_IMAGES（URL配列）。rkSave payload に image_urls、rkFillForm で note.image_urls から復元。RK_ALL_FIELDS に ['image_urls','写真'] 追加。

### 30-2. 写真をLINE送信（第三段階）
- **マーカー `renraku-line-photo-v1`（app.py）**:
  - `_line_push` の messages[:3] → messages[:5]（LINE仕様: 1pushで最大5メッセージ）。
  - `_line_image_messages(urls)`: https URLから `{type:'image', originalContentUrl, previewImageUrl}` を生成（https以外は除外）。
  - `_line_push_chunked(token, uid, messages)`: messages を5件ずつ分割して順にpush。
  - api_renraku_line_send: data から image_urls 受領（送信APIは text を受け取る方式のため note でなくフロントから渡す）。messages = テキスト + 画像メッセージ、_line_push_chunked で送信。
  - api_renraku_line_preview: 戻りに photo_count 追加。
- **マーカー `renraku-line-send-images-v1`（renraku.html）**: rkLineSend の送信 body に image_urls:RK_IMAGES を追加。
- **実機確認**: 青木さんに写真6枚添付→LINE送信。テキスト1+画像6=7メッセージ→5件+2件の2回pushに自動分割。HIRO🐻❄️のLINEに整形テキスト＋写真が届くことを確認。case-photos公開URLがLINEから取得可能（HEAD 200/image/png）であることも実証。

### 30-3. 運用メモ・教訓
- **ブラウザキャッシュ注意**: デプロイ直後、ブラウザが古いJS（image_urlsを渡さない版のrkLineSend）を保持していると写真が送られない。デプロイ後はリロード（必要ならスーパーリロード）してから送信テストすること。最初「写真が届かない」と見えたのはこれが原因だった。
- 写真プライバシー: case-photos は公開バケット（既存ケース記録と同じ扱い）。LINE送信は写真URLを家族に渡すことになる。当面は既存ケース記録と同じ基準で運用。プライバシー強化が必要なら署名付きURL方式へ後日移行可能。

### 30-4. 今セッションのコミット（DEV、tasukaru-dev）
03bbb3e 写真添付API+UI(第二段階) / e3c60cb 写真LINE送信(第三段階)。

## 31. LINE本番反映＋記録/掲示板/評価の改善（2026-06-24）<!-- readme-s31-session64 -->

SESSION_64。LINE連携＋連絡帳写真を**本番反映**し、記録入力・掲示板・評価まわりの不具合4件を修正（すべてDEV→本番反映済み）。

### 31-1. LINE連携＋連絡帳写真の本番反映（完了）
- **本番Supabase DDL適用**（コードより先・冪等）: `line_friends`（9列・PK=id・unique(facility_code,line_user_id)）/ `line_settings`（7列・PK=facility_code・channel_access_token_enc/channel_secret_enc/line_oa_name/enabled）/ `renraku_notes.image_urls`(jsonb)。DEV実テーブルと照合して確定。
- **本番Cloud Run** に `LINE_TOKEN_ENC_KEY`（本番用の別Fernet鍵）設定。既存env温存。鍵はHIROが手元生成・保管（チャットに平文露出なし）。
- **コード反映**: DEVの4ファイル（app.py / templates/admin.html / templates/renraku.html / templates/base.html）を**ファイル単位で本番へ**（`git checkout tasukaru-dev -- <files>`）。カレンダーは calendar.html のみで今回の4ファイルに含まれず、本番のカレンダーcherry-pick(c107a40)を巻き戻さない。本番コミット dda0ed1。
- **LINEチャネル繋ぎ替え**: 運用中の公式アカウント「機能訓練型デイサービス【ココカラプラス】」にMessaging API有効化（プロバイダー=同名・後変更不可）。Webhook URL=`https://tasukaru-191764727533.asia-northeast1.run.app/line/webhook/cocokaraplus-5526`、Webhookオン、検証200成功。あいさつメッセージはオン維持（プッシュ送信と競合せず両立可）。本番admin画面に token/secret 入力＋enabled。実機で友だち受信（unlinked保存・display_name取得）確認。
- **注意/未了**: 新規作成した別アカウント「【公式ココカラプラス】利用者連絡帳」は紛らわしいので削除予定（繋ぎ替え完了後）。既存の友だち（家族）は繋いだ時点では line_friends に自動で入らず、家族が一度メッセージ送信/再追加した時にWebhook受信して登録される（運用で取り込む）。

### 31-2. 記録入力の保存スピナー（inp-save-spinner-v1・本番反映済み）
templates/input.html。saveRecord は押下後すぐAIカテゴリ提案(/api/records/suggest_category)をawaitしモーダル応答も待つため「保存中」表示が遅れていた。修正: 押下直後に即「カテゴリ確認中...」(回転sync)→モーダル中は通常復帰→POST中「保存中...」。本番コミット 2f628e8。

### 31-3. 掲示板の確認済みボタン（board-toggle-optimistic-v1・本番反映済み）
templates/board.html。症状「1回で反応せず2度押すと反応／確認したのに未読に戻る」。Chrome連携(MCP)で原因特定: サーバーAPI・DB保存・JS判定は全て正常（toggleCheck直接呼び出しで確認済み⇄未確認が正しく動作）。真因は (1)押下後 pointerEvents='none' のまま通信完了まで無効化されタップが死ぬ (2)視覚フィードバック欠如で二度押し→トグルなので確認済みが未読に戻る。修正: 楽観的UI更新（押下即トグル＋処理中の薄表示）＋API成功でサーバー確定状態に同期＋失敗時ロールバック＋dataset.busyで連打ガード。本番コミット 1e80935。

### 31-4. 評価AI生成の改善（eval-aifill-tone-v1 / eval-aifill-medical-v1・本番反映済み）
app.py /api/evaluation/ai_fill のプロンプト。(1)文字化け「堂すぎず碕けず」→「硬すぎず砕けすぎず」修正＋二重敬語禁止を明示。(2)機能訓練指導員（PT/OT/ST/柔整/看護師等）として医学的視点・機能訓練の専門的観点（身体機能・ADL・関節可動域・筋力・バランス・歩行・認知/嚥下機能等）を踏まえる、を明示。Chrome連携でテキスト元データを投入し品質確認（数値正確・ハルシネーション無・自然な口調）。

### 31-5. 評価メモ文字起こしの改善（eval-transcribe-filler-v1 / eval-ingest-order-v1・本番反映済み）
app.py /api/evaluation/ingest_file。(1)両モード(dialog/solo)のフィラー方針を「そのまま記載」→「フィラー・言いよどみ・無意味な繰り返しは除去し読みやすく整える（内容は変えない）」に変更。(2)プロンプト混入バグ: generate_content([{音声}, prompt]) の順で音声→指示の流れになりGeminiが指示文まで出力に混入＋フィラー指示も効かず。generate_content([prompt, {音声}]) に順序逆転して解消（音声側のみ・画像側L5145は触らず）。実機（音声録音）で混入消失・フィラー除去を確認。
※評価メモ欄とは別に /api/transcribe も存在（こちらは元からフィラー省略指示あり）。

### 31-6. 教訓
- 長文のヒアドキュメント貼り付けはターミナルで化けやすい。app.pyの小さな日本語置換は `python3 -c "..."` の1行版が安全（marker確認＋count assert＋.bak付き）。
- README追記は従来どおり `cat >>`（Python全文書き直し厳禁）。今回も §31 を末尾追記し wc -c で増加確認。

### 31-7. 次タスク候補
- 新規LINEアカウント「利用者連絡帳」の削除。
- 既存友だち(家族)の line_friends 取り込み運用の設計（案内文等）。
- admin LINE設定ガイド: 外部ドキュメント(Notion等)へのリンク方式で作成予定（施設職員向けに設定手順を丁寧に）。たたき台の手順文はSESSION_64の操作ログが素材。

## 32. 掲示板「確認済みが未確認に戻る」問題の根治（2026-06-25）<!-- readme-s32-session65 -->

SESSION_65。掲示板で「確認ボタンを押しても確認済みにならず未確認に戻る／未読が増える」という長期の不具合を、Chrome連携(MCP)で本番ライブ調査し、真因を特定して根治。対症ではなく構造的修正まで実施。本番反映済み。

### 32-1. 症状と最初の誤診
- 症状: 確認ボタンを押すと一瞬「確認済み」になるが離す/スクロールすると「未確認」に戻る。押すと未読数が増えることもある。本番・PC両方で再現。
- 当初はフロント(楽観的UI更新 board-toggle-optimistic-v1)やタッチイベント、リロードを疑ったが、いずれも主因ではなかった。Chrome連携でクリック・toggleCheck発火・fetch応答・DOM変化・reload呼び出しを逐一計測して切り分けた。

### 32-2. 調査途中で見つかった副次バグ（先に修正・本番反映済み）
- **board-poll-singleton-v1**: 掲示板の新着ポーリング `startRealtime()` が SPA 再注入のたびに `setInterval(boardPollNew)` を張り直し、本番で **56個並走**していた。`window._boardPollTimer` で常に1本に。本番コミット e4437d3。
- **board-poll-noreload-v1**: `boardPollNew` の新着検知時 `setTimeout(window.location.reload)` が楽観的UI更新を巻き戻す元凶になり得たため、ページ全体の自動リロードを廃止。新着はトースト通知＋未読バッジ更新のみに変更。本番反映済み。

### 32-3. 真因（board-checks-pagination-v1 → board-paginate-helper-v1）
- **真因はサーバー側 `board()` の `checks_data` 構築**。`supabase.table("board_checks").select(...).in_("post_id", post_ids).execute()` に `.range()` が無く、**Supabaseのデフォルト1000行上限**で古い投稿(若いID)の確認済みレコードが取りこぼされていた。
- 結果、**画面=未確認(赤) なのに DB=確認済み** というゴースト投稿が発生。ユーザーが赤を押す→サーバーはDBの真の状態(確認済み)を見て `removed`(外す)→確認済みにならず未読が増える。
- Chrome連携で実証: 本番で岸本の確認済みは初期描画131件しか取れていなかったが、DB実体は162件。未触の投稿8件中7件がゴースト(画面未確認・DB確認済み)だった。
- 修正: まず `board_checks` のみ `range()` ページング化(board-checks-pagination-v1)。その後、他施設展開を見据え**共通ヘルパー `_fetch_all_paginated(make_query, page_size=1000, max_pages=50)`** を新設し、`board()` 内の取得系4クエリ(board_comments / board_reactions / board_reads / board_checks)を全件ページング取得に統一(board-paginate-helper-v1)。reactions/reads には `facility_code` 絞りも追加。本番反映後、確認済み 162件=DOM 162件で整合確認。

### 32-4. 教訓
- **`.in_(...).execute()` でまとめ取得している箇所は、データ増で必ず1000行上限に当たる。** 「画面とDBが食い違う」系の不具合はこれを疑う。今後の大量取得は `_fetch_all_paginated()` を使う。
- 症状の見た目(UIが戻る/リロードされる)に引きずられず、サーバーが返す確定値(toggle応答の action と checked_names)を直接見ると早い。`action:"removed"` が出たら「押す前からDB上は確認済み」=ゴーストのサイン。
- Chrome連携の計測は、監視ラッパ(location.reload上書き等)自体が挙動を変えうる。素の再現と計測を分けて考える。
- ヘルパーはクエリビルダを使い回さず「毎回ビルダを返すラムダ」を受ける方式にした(supabase-py のバージョン非依存・再 .range() 安全)。

### 32-5. 次タスク候補
- 同パターンの他ルート(board以外で `.in_(...).execute()` を使う箇所)を `_fetch_all_paginated()` に順次移行。
- `/calendar` の `CalendarBarConnect ... reading 'top'` エラー(既存・fallback動作中)の調査。
- DEVのダミー投稿(post_id 13〜22)は検証用に残置中。不要になれば削除。

## 33. 休み連絡の連絡者バッジ化 ＋ UI幅揃え（2026-06-25）<!-- readme-s33-session65 -->

SESSION_65後半。休み連絡カテゴリの「連絡者」表示改善（文章→バッジ分離、無断欠席=連絡なし追加）と、掲示板/TOP/ボトムナビ/生活機能チェックのUI幅揃え。すべてDEV検証後に本番反映済み。

### 33-1. 休み連絡の連絡者バッジ化
- **方針**: ケース記録のcontentから連絡者文章を分離。日付・理由はそのまま、連絡者は「休み連絡」カテゴリタグの右横にバッジ表示。「連絡なし」（無断欠席）を選択肢に追加し赤で目立たせる。
- **leave-reporter-display-v1**: `_build_leave_content`（app.py 819付近）を「{period}はお休みです。理由：…」に変更し連絡者を文章から除去（reporter_type/other_detailは互換のため引数に残す）。`_reporter_map_n`（app.py 9931付近・モニタリング側）に `none:連絡なし` 追加。input.html に「連絡なし」ボタン（`data-leave-type="none"`）＋赤スタイル`.leave-btn-none.selected`＋アラート文言調整。daily_view.html のバッジを全タイプ対応（self/family(関係性)/caremanager/other/none）、noneは赤クラス。
- **leave-badge-in-modal-v1**: 個別記録モーダル `openRecordsModal`（daily_view.html 3499付近）は records-hidden 内の各記録から meta/content/category/vas/photo/actions を**個別に拾い再構築**する方式のため、連絡者バッジが欠落していた。`.leave-reporter-badge` を拾って差し込む処理を追加。
- **leave-badge-inline-v1**: バッジを `<div>`→`<span>`化しアイコン除去（文言「連絡：○○」、noneは「連絡：連絡なし」）。モーダルでカテゴリタグとバッジを flex 横並び（カテゴリ右横）に。
- **leave-badge-textonly-v1**: バッジの背景枠を撤廃し文字のみ（noneは赤文字）。モーダルheaderの meta を `textContent` で取ると material-symbols のリガチャ名（schedule/label/edit）が文字化けするため、meta を clone→`.material-symbols-outlined` 要素を除去してからテキスト化。
- **注意**: 過去の休み連絡レコードはcontentに旧文章「○○から連絡がありました」が残る（新規入力分から新仕様）。一括更新は未実施。
- **構造メモ**: daily_view は「利用者アコーディオン→AI要約→個別記録N件を見る（openRecordsModal）」の構造。個別記録は `records-hidden-{idx}`（display:none）に格納され、モーダルが再構築して表示。要素を足すときは openRecordsModal の再構築ロジックに拾う処理が必要。`leave_reporter_type` 値: self/family/caremanager/other/none。

### 33-2. UI幅揃え・微調整
- **top-lcalert-height-v1**（top.html）: TOP生活機能チェック枠の高さをタスク枠に揃える。原因は `.lcalert-header` に margin-bottom が無く `.birthday-header`(margin-bottom:10px)より10px低かった→ `.lcalert-header` に margin-bottom:10px。
- **board-posts-padtop-v1**（board.html）: 最初の投稿がstickyヘッダー(.board-sticky-stack)に潜り込む→ `#posts-container` に padding-top:12px。
- **board-header-align-v1**（board.html）: `.board-tabs-wrap` の左右padding 12px→0（タブを投稿カード/検索窓の端へ）。
- **board-fullbleed-v1**（board.html）: タブ帯・検索窓・投稿カードを page-wrapper の白背景の端まで広げて揃える。page-wrapperの左右padding(1.2rem)を負マージンで相殺（`#posts-container` margin -1.2rem、`.board-tabs-wrap` margin -1.2rem+padding 1.2rem、`.board-search-bar` margin -1.2rem）。
- **bottomnav-pad-align-v1/v2・bottomnav-fullbleed-v1**（base.html）: ボトムナビ幅を本文（白背景端）に揃える試行錯誤。v1=padding追加（box-sizing:border-boxで外枠幅変わらず無効）→v2=`max-width: calc(--page-max-width - 2.4rem)`（内容幅）→最終 fullbleed=`max-width: var(--page-max-width)`（白背景端）。最終的にタブ/検索/投稿カード/ナビ/本文すべて同一左右端で一致。
- **lc-total-navwidth-v1**（life_check.html）: 生活機能チェックのADL合計固定バー `.lc-total` の max-width 720px→`var(--page-max-width)`（ボトムナビと同幅）。本文 `.lc-wrap`(720px) は変更せず。

### 33-3. 教訓
- 固定/sticky要素の幅は page-wrapper の左右padding(1.2rem)を意識する。**box-sizing:border-box では padding を足しても外枠幅は変わらない**ので、幅を変えたいときは max-width か negative margin を使う。
- 要素境界(getBoundingClientRect)が揃っているのに見た目がズレる時は、Chrome連携で**ガイド線をDOMに描画**して視覚確認すると食い違いの正体が早く分かる（今回「白い部分」=page-wrapperの白背景端であり、中の要素がpadding内側にあったのが原因と判明）。
- ライブで `element.style.xxx` を当てて揃うことを先に検証してから、確定パッチを作ると往復が減る。

### 33-4. 次タスク候補（生活機能チェックのBI切替）
- 要支援・事業対象者はBI（バーセルインデックス）、要介護は生活機能チェックシート（様式3-2）。利用者選択で介護度を自動表示し、どちらかに手動切替も可能にする構想。要確認: 介護度データ（要支援/要介護/事業対象者）が patient_profiles 等に保存されているか。未保存なら介護度入力の仕組みから。
