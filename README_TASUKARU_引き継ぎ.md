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

