# TASUKARU 出納帳開発ログ・引き継ぎドキュメント

## プロジェクト基本情報

| 項目 | 内容 |
|---|---|
| リポジトリ | cocokaraplus-max/kaigo-ai-app |
| ローカル | `/Users/ZIMAX 1/dev/kaigo-ai-app/` |
| dev URL | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| prod URL | https://tasukaru-191764727533.asia-northeast1.run.app |
| dev Supabase | `otjevnmoycnvaxeltrtj`（施設コード: DEMO001） |
| prod Supabase | `abvglnkwtdeoaazyqwyd`（施設コード: cocokaraplus-5526） |
| Cloud Build | プロジェクト: `tasukaru-production`、リージョン: `asia-northeast1` |

---

## ブランチ運用ルール（重要）

```
tasukaru-dev → 開発・テスト用
tasukaru     → 本番用
```

### 標準デプロイ手順

```bash
# 1. devにコミット・プッシュ
cd "/Users/ZIMAX 1/dev/kaigo-ai-app"
git checkout tasukaru-dev
git add .
git commit -m "feat: 変更内容"
git push origin tasukaru-dev

# 2. devビルド確認後、prodにマージ
git checkout tasukaru
git merge tasukaru-dev
git push origin tasukaru
git checkout tasukaru-dev
```

### 誤ってtasukaruブランチにコミットした場合

```bash
# devにcherry-pickして、tasukaruの誤コミットを取り消す
git checkout tasukaru-dev
git cherry-pick tasukaru
git push origin tasukaru-dev
git checkout tasukaru
git reset --hard HEAD~1
git push origin tasukaru --force
git checkout tasukaru-dev
```

### コンフリクト時

```bash
git checkout --theirs app.py
git add app.py
git commit -m "merge: コンフリクト解決"
git push origin tasukaru
```

---

## ファイル編集ルール（重要）

- **日本語を含むヒアドキュメント（`<< 'EOF'`）は使わない** → ターミナルで文字化け・構文エラーが発生する
- 代わりに **Pythonスクリプトをダウンロードして実行** する方式を使う
- スクリプトはダウンロードしてデスクトップに保存後 `python3 ~/Desktop/fix_xxx.py` で実行

```python
# スクリプトのテンプレート
with open('/Users/ZIMAX 1/dev/kaigo-ai-app/templates/ledger.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 修正処理
html = html.replace('old', 'new')

with open('/Users/ZIMAX 1/dev/kaigo-ai-app/templates/ledger.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('done')
```

---

## セキュリティ注意事項

### APIキー・シークレットの扱い
- **絶対にチャットや出力にAPIキーを露出させない**
- Supabaseの接続情報、AnthropicのAPIキーなどはすべて環境変数で管理
- コード中に直接書かない。例：
  ```python
  # NG
  client = Anthropic(api_key="sk-ant-...")
  
  # OK
  client = Anthropic()  # ANTHROPIC_API_KEY環境変数から自動読み込み
  ```
- もしチャットにキーが表示されてしまったら、即座にそのキーをローテーション（無効化→再発行）すること

### Supabase SQL実行時
- DevとProdを混同しないよう注意
- Dev: `otjevnmoycnvaxeltrtj`
- Prod: `abvglnkwtdeoaazyqwyd`
- 必ずURLを確認してから実行する

---

## 出納帳機能 実装済み一覧

### DBテーブル（dev・prod両方に適用済み）
```sql
-- journal_entries に追加
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS division_id BIGINT DEFAULT NULL;

-- ledger_settings に追加
ALTER TABLE ledger_settings ADD COLUMN IF NOT EXISTS cash_fill_division_id BIGINT DEFAULT NULL;
```

### バックエンド（app.py）実装済み
| API | 説明 |
|---|---|
| `GET /api/ledger/settings` | 設定取得（cash_fill_division_id含む） |
| `POST /api/ledger/settings` | 設定保存 |
| `GET /api/ledger/entries` | 仕訳一覧（division_idフィルタ対応） |
| `POST /api/ledger/entry` | 仕訳保存（division_id対応） |
| `DELETE /api/ledger/entry/<id>` | 仕訳削除（再計算トリガー付き） |
| `POST /api/ledger/transfer` | 事業間資金移動（2仕訳自動生成） |
| `POST /api/ledger/cash_fill` | 現金自動補填 |
| `POST /api/ledger/import_csv` | CSV取込（AI解析・確認後保存） |
| `POST /api/ledger/ocr_receipt` | 領収書OCR |
| `_ledger_recalc_day()` | 現金残高自動再計算エンジン |

### フロントエンド（ledger.html）実装済み
| 機能 | 説明 |
|---|---|
| 仕訳帳 | 事業部バッジ表示、事業部フィルター |
| 現金出納帳 | 事業部列、事業部フィルター、期首残高設定 |
| 預金出納帳 | 期首残高設定 |
| 事業間移動モーダル | ⇄ボタンから移動元・移動先・金額入力 |
| 自動再計算 | 仕訳追加・編集・削除時に自動補填見直し |
| 現金自動補填 | 設定タブから補填元事業部を指定 |
| CSV取込 | AI自動科目推定→プレビュー→確認後保存 |
| 領収書OCR | 複数枚同時アップロード対応 |

---

## 自動再計算ロジック（重要）

```
仕訳追加・編集・削除
      ↓
_ledger_recalc_day(supabase, f_code, target_date) 呼び出し
      ↓
設定確認: auto_cash_fill = ON の施設のみ実行
      ↓
当日の手動仕訳を集計
  - 経費合計（現金が貸方、費用科目が借方）
  - 銀行→現金入金合計（普通預金が貸方、現金が借方）
      ↓
不足分 = 経費合計 - 銀行入金合計
      ↓
既存の auto_fill 仕訳を全削除
      ↓
不足分 > 0 なら：
  - 補填元事業部から現金移動（出金仕訳）→ division_id = fill_div_id
  - 全事業への現金移動（入金仕訳）→ division_id = null
```

---

## TDZ（Temporal Dead Zone）問題について

JavaScriptの `let`/`const` は宣言前に参照するとエラーになる。
`openEntryModal` が `loadSettings` より前に定義されているため、
`let` で宣言した変数を使えない問題が発生した。

**解決策**: グローバル変数は `window.xxx = []` 形式で宣言する

```javascript
// NG
let allAccounts = [];      // TDZ問題が起きやすい
let currentDivisions = []; // 同上

// OK
window.allAccounts = [];
window.currentDivisions = [];
window.currentSettings = {};
```

---

## 既知の残課題・TODO

### 優先度高
- [ ] `renderEntries` の初回ロード時に `loadSettings` の完了を待ってから実行する仕組み（現状は手動リロードで解決）
- [ ] `printSubLedger`（PDF印刷）がポップアップブロックされる場合の対処
- [ ] 仕訳帳フィルターで事業部を切り替えた時の収益・費用合計の事業部別集計

### 優先度中
- [ ] CSVプレビュー画面のUI改善（事業部選択欄の追加）
- [ ] 現金出納帳の期首残高をlocalStorageではなくDBで永続管理
- [ ] 試算表の事業部別表示

### 優先度低
- [ ] 事業間移動の自動再計算への組み込み（現状は手動移動のみ）
- [ ] Excel出力に事業部列を追加

---

## 作業の進め方（AIへの引き継ぎ）

### 基本方針
1. **変更前に必ず現状確認** → `grep` や `sed` でコードを確認してから修正
2. **一度に大きく変えない** → 小さな修正をこまめにコミット・ビルド確認
3. **devでテストしてからprodマージ** → ビルドが✅になってからmerge
4. **ファイル修正はPythonスクリプト経由** → ヒアドキュメント禁止

### ビルド確認URL
https://console.cloud.google.com/cloud-build/builds;region=asia-northeast1?project=tasukaru-production

### Supabase SQL実行
- Dev: https://supabase.com/dashboard/project/otjevnmoycnvaxeltrtj/sql/new
- Prod: https://supabase.com/dashboard/project/abvglnkwtdeoaazyqwyd/sql/new

---

## 次のチャットへの引き継ぎ文章

以下の文章を次のチャットの冒頭にコピー＆ペーストしてください。

---
