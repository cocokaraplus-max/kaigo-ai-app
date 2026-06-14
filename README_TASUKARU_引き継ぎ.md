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


