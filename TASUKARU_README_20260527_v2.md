# TASUKARU 開発セッション記録
**日付**: 2026-05-27  
**最終コミット**: `0effefe`  
**ブランチ**: `tasukaru-dev` → `tasukaru`（本番マージ済み）

---

## 環境情報

| 項目 | 値 |
|---|---|
| リポジトリ | cocokaraplus-max/kaigo-ai-app |
| ローカル | `/Users/ZIMAX 1/dev/kaigo-ai-app/` |
| dev | https://tasukaru-dev-191764727533.asia-northeast1.run.app |
| prod | https://tasukaru-191764727533.asia-northeast1.run.app |
| 開発ブランチ | `tasukaru-dev` |
| 本番ブランチ | `tasukaru` |

---

## Cloud Build トリガー構成

| トリガー名 | ブランチ | 用途 |
|---|---|---|
| `tasukaru-dev-auto-deploy` | `^tasukaru-dev$` | dev自動デプロイ |
| `rmgpgab-tasukaru-asia-northeast1-...` | `^tasukaru$` | 本番自動デプロイ |

**注意**: トリガーはglobalリージョンに1つずつ。asia-northeast1リージョンに重複トリガーが作られると2重ビルドになるので注意。

**本番マージコマンド**:
```bash
cd '/Users/ZIMAX 1/dev/kaigo-ai-app' && git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru && git checkout tasukaru-dev
```

---

## Cloud Run メモリ設定

| サービス | メモリ |
|---|---|
| `tasukaru-dev` | 2GB（PDF生成のため増強済み） |
| `tasukaru` | 2GB（PDF生成のため増強済み） |

メモリ変更コマンド:
```bash
gcloud run services update tasukaru-dev --project=tasukaru-production --region=asia-northeast1 --memory=2Gi
gcloud run services update tasukaru --project=tasukaru-production --region=asia-northeast1 --memory=2Gi
```

---

## 本日の作業内容（本番マージ済み）

### 1. 書類出力ページ UI修正

**ファイル**: `templates/print_output.html`

- **テンプレートグリッド**: 5列 → 4列に変更（中央カードが大きく見える崩れを修正）
- **データ充足チェックテーブル**:
  - `table-layout: fixed` + `colgroup` で列幅を明示的に制御
  - ヘッダー横書き化・ケアマネ列折り返し対応
  - 確認・印刷ボタンを縦並びに変更

### 2. タスカル君ローディングアニメーション追加

**ファイル**: `templates/print_output.html`

確認・印刷・全員印刷ボタン押下時にタスカル君歩行オーバーレイを表示。  
`setTimeout 300ms` で遷移前にアニメーションを表示してから `window.location.href` で遷移。

```javascript
function poShowLoading(label) { ... }
function poHideLoading() { ... }
```

### 3. プレビュー/印刷の動作分離

**ファイル**: `templates/print_output.html`

- `poPreviewAll()` が `poPrintAll()` を呼んでいたため印刷ダイアログが出ていた → 独立した関数に分離
- `auto_print=1` の付与/非付与を正しく制御

| ボタン | 動作 |
|---|---|
| 確認 | `/print_preview`（印刷ダイアログなし） |
| 印刷 | `/print_preview?auto_print=1`（印刷ダイアログあり） |
| 全員印刷 | `/print_preview?auto_print=1`（印刷ダイアログあり） |
| プレビューで確認 | `/print_preview`（印刷ダイアログなし） |

### 4. PDF直接出力（WeasyPrint → wkhtmltopdf切り替え）

**ファイル**: `Dockerfile`, `requirements.txt`, `app.py`

**経緯**:
- WeasyPrintはCloud Run 512MBでメモリ不足（SIGKILL）
- 2GBに増やしても1人分でSIGKILL
- wkhtmltopdfに切り替えで解決

**Dockerfile変更**:
```dockerfile
# wkhtmltopdf公式debパッケージを直接インストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-noto-cjk \
    libssl3 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    && curl -L https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb -o /tmp/wkhtmltox.deb \
    && apt-get install -y /tmp/wkhtmltox.deb \
    && rm /tmp/wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/*
```

**requirements.txt**: `weasyprint` → `pdfkit`

**app.py `/print_pdf` ルート**:
- `pdfkit.from_string()` でPDF生成
- `shutil.which('wkhtmltopdf')` でパスを動的検出
- `Content-Disposition` ファイル名をRFC5987形式（`filename*=UTF-8''...`）でエンコード

**注意**: wkhtmltopdfはChart.js等のJSグラフを描画しない（サーバーサイドレンダリングのため）。グラフはPDFに出ない。

### 5. あり・なしチェックボックスの縦位置修正

**ファイル**: `templates/print_preview.html`

`vertical-align:middle` と `flex-shrink:0` を追加。

---

## Gitコミット履歴（今セッション）

| コミット | 内容 |
|---|---|
| `eb2f9b5` | テンプレート4列・チェックテーブルレイアウト修正 |
| `e3efc43` | タスカル君ローディングアニメーション追加 |
| `b69ed1a` | ローディング遅延修正（setTimeout 300ms） |
| `8d4969e` | poPreviewAllをauto_printなしに修正 |
| `8a997cd` | Dockerfile WeasyPrint依存パッケージ修正（失敗） |
| `43c0f09` | libgdk-pixbufパッケージ名修正（失敗） |
| `19611bf` | wkhtmltopdfへ切り替え |
| `cc11c14` | wkhtmltopdf公式debパッケージ使用 |
| `34a8417` | SyntaxError修正（壊れたtry/except削除） |
| `eab3b11` | wkhtmltopdfパス動的検出 |
| `13f42bc` | Content-Dispositionファイル名エンコード |
| `b94559d` | fstring構文エラー修正 |
| `0effefe` | あり・なしチェックボックス縦位置修正 |

---

## 残タスク

### 🟡 中優先度

#### 1. PDFグラフ出力
- wkhtmltopdfはJSを実行しないためChart.jsグラフがPDFに出ない
- 対応候補: Chart.jsをサーバーサイドで画像化（QuickChart API等）またはPython側でmatplotlib等で描画

#### 2. 要介護利用者の目標達成状況確認
- 機能・活動・参加の3分類が正しく表示されるか確認

#### 3. 複数ブラウザでのプレビューレイアウト確認
- 特にtmpl-4（サイドバーテンプレート）

---

## 重要ルール（次回セッション引き継ぎ）

1. **日本語含むヒアドキュメント禁止** → Pythonスクリプトをcreate_toolで作成してダウンロード方式
2. **APIキー等はコードに記載禁止**
3. **dev確認 → 本番マージの順序厳守**
4. **Cloud Buildトリガーはglobalに1つずつ**（asia-northeast1に重複作成しない）
5. **本番マージコマンド**:
   ```bash
   cd '/Users/ZIMAX 1/dev/kaigo-ai-app' && git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru && git checkout tasukaru-dev
   ```
