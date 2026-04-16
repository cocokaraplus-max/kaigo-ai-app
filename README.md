# TASUKARU 開発記録 🦝

> **このREADMEを読む君（次のClaude）へ**
>
> このプロジェクトはオーナー（ZIMAX、以下「開発者」）と長い時間をかけて作り上げている介護記録アプリです。
> 開発者はエンジニアではありません。「現場のスタッフが迷わず使える」ことを最優先にしてください。
>
> **⚠️ 重要：開発者のMacはパスにスペースがあります**
> プロジェクト：/Users/ZIMAX 1/Desktop/kaigo-ai-app/
> cpコマンド：cp "/Users/ZIMAX 1/Downloads/xxx" templates/
>
> **⚠️ ファイルの受け渡し方法（重要）**
> VS Codeのターミナルを使うのが確実。
> Claudeはコード変更があれば完成版ファイル全体を出力して、VS Codeに貼り付けてもらう。
> またはpythonパッチスクリプト（patch_xxx.py）をtemplatesに置いてpython3で実行する方法が定着。
>
> **⚠️ sw.jsは絶対に触らない**
> バージョンを上げると真っ白になる。現在：tasukaru-v4（固定）
>
> **⚠️ Chrome連携（Claude in Chrome）が使える**
> 開発者のChromeと連携しており、スクリーンショット・JS実行・コンソール確認が可能。
> デプロイ前の動作確認はChrome連携で必ず行う。

---

## プロジェクト概要

- **アプリ名**：TASUKARU（タスカル）🦝
- **目的**：介護現場の記録業務をAIで自動化・効率化
- **技術スタック**：Python/Flask, Supabase(PostgreSQL), Gemini AI, Google Cloud Run
- **本番URL**：https://tasukaru-191764727533.asia-northeast1.run.app
- **開発URL**：https://tasukaru-dev-191764727533.asia-northeast1.run.app
- **GCPプロジェクト**：tasukaru-production（PROJECT_NUMBER: 191764727533）
- **Supabase**：abvglnkwtdeoaazyqwyd（ap-northeast-1）
- **施設コード**：cocokaraplus-5526

---

## デプロイコマンド（完全版）

```bash
# 開発版
cd "/Users/ZIMAX 1/Desktop/kaigo-ai-app"
git add .
git commit -m "変更内容"
git push origin cloudrun-dev
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --platform managed --allow-unauthenticated

# 本番同期（マージコンフリクト回避のため checkout方式を使う）
git checkout cloudrun
git checkout cloudrun-dev -- app.py
git checkout cloudrun-dev -- templates/base.html
git checkout cloudrun-dev -- templates/top.html
git checkout cloudrun-dev -- templates/manual.html
git add .
git commit -m "sync: cloudrun-devの内容を本番に反映"
git push origin cloudrun
gcloud run deploy tasukaru --source . --region asia-northeast1 --platform managed --allow-unauthenticated
git checkout cloudrun-dev
```

**⚠️ git merge は.DS_Storeとかでコンフリクトするのでcheckout方式を使うこと！**

---

## 2026-04-16 大規模修正セッション完了内容

### ✅ 本番デプロイ済み

| # | ファイル | 修正内容 |
|---|---------|---------|
| 1 | app.py | input_viewのXHR保存修正（X-Requested-With判定でJSON返却） |
| 2 | app.py | 評価プロンプト全面改善（ICF視点・機能訓練指導員口調） |
| 3 | app.py | 全APIバリデーション強化（save_vital/generate_daily等） |
| 4 | app.py | 更新履歴をcreated_at順→id降順に変更（未来日付が上に来なくなった） |
| 5 | base.html | ベルはTOPのみ表示・歯車もTOP以外は非表示（applyFabVisibility） |
| 6 | base.html | history-itemクリック→ケース記録ジャンプ（イベント委譲で実装） |
| 7 | base.html | ベルのないページからはTOPへSPA遷移 |
| 8 | top.html | 更新ログモーダルHTML追加（ベルを押すと開く） |
| 9 | top.html | 歯車CSS(position:fixed)削除・歯車HTMLボタン削除 |
| 10 | top.html | fabBtn/openIconBtnのnullガード追加 |
| 11 | manual.html | 上に戻るボタン bottom:130px・scrollTo修正 |

### ⚠️ 残っているJS nullエラー
- top.html 2676行目にまだnullエラー残存
- patch_top.pyのfabBtn/openIconBtn nullガードは適用済みだが別箇所にまだある可能性
- Chrome連携で `read_console_messages` して特定→修正が必要

---

## base.htmlの重要な構造

```
【top-fab-area】（body最後尾にmoveFabToBodyで移動）
  - #update-log-btn（ベル）← TOPのみ表示
  - #settings-fab-btn（歯車）← TOPのみ表示

【applyFabVisibility()】
  - isTop = pathname === '/top' || '/'
  - fabArea/bellBtn/gearBtn を isTop ? '' : 'none'
  - popstate・pushStateにフック済み

【イベント委譲（document.addEventListener click）】
  - .history-item[data-user] → /daily_view?user=&date= へジャンプ
  - #update-log-btn → update-log-modalを開く（なければ/topへ）
  - #settings-fab-btn → openSettings()
  - #close-update-log-btn → モーダルを閉じる
```

---

## タスクのプロジェクト機能（よくある質問）

「なし」しか選べない → プロジェクトを先に作成する必要がある
「タスク」→「プロジェクト」タブ → 「新しいプロジェクトを作成」
プロジェクト名を入力してメンバーを選んで作成
→ タスク作成時にプロジェクト選択肢に出てくる
→ マニュアルにも手順を追記済み（patch_manual_project.py適用後）

---

## 📊 2026-04-16 新規作業：Googleスプレッドシート連携

### 概要
ケース記録・モニタリング報告書のExcel様式をGoogleスプレッドシートで管理し、
TASUKARUのデータを自動入力できる仕組みを構築中。

### 完了済み
1. **ExcelテンプレートをGoogleスプレッドシートに変換**
   - 元ファイル：ケース記録_モニタリンク_.xlsx（4シート構成）
   - 変換済みファイル：TASUKARU_様式（Googleスプレッドシート）
   - GoogleドライブURL：https://docs.google.com/spreadsheets/d/13fAq0ELCyq8w_bryzt-CEpKrzdDdsPyqYd-UYEqLq6Q/edit
   - 保存場所：マイドライブ > ケース記録＆モニタリング フォルダ
   - 書式確認済み（ほぼ崩れなし）

2. **Google Apps Script（GAS）コード作成済み**
   - GASプロジェクト名：TASUKARU自動入力
   - スクリプトID：1_3CHezNwUFpBMchQv7cMWCS4qU7R_32glKcDankYrHBuLZdpqOz0OpsL
   - Apps Script URL：https://script.google.com/u/0/home/projects/1_3CHezNwUFpBMchQv7cMWCS4qU7R_32glKcDankYrHBuLZdpqOz0OpsL/edit
   - 機能：
     - スプレッドシートに「🦝 TASUKARU」メニューを追加
     - 利用者一覧をSupabaseから取得してダイアログ表示
     - 選択した利用者のデータをシートに自動入力
     - 設定画面でSupabase APIキーを保存

3. **スクリプトプロパティの設定画面まで到達**
   - プロパティ名「SUPABASE_KEY」は入力済み
   - **値（Supabase Anon Key）の貼り付けがまだ未完了** ← ここで止まっている

### ❌ 次のセッションでやること（最優先）

**① GASにSupabase Anon Keyを設定する**

手順：
1. Chromeで https://script.google.com を開く
2. 「TASUKARU自動入力」プロジェクトを開く
3. 左メニューの歯車アイコン「プロジェクトの設定」をクリック
4. 下にスクロールして「スクリプトプロパティ」セクションへ
5. 「スクリプトプロパティを追加」をクリック
6. プロパティ：`SUPABASE_KEY`
7. 値：SupabaseのAnon Key（下記から取得）
   - https://supabase.com/dashboard/project/abvglnkwtdeoaazyqwyd/settings/api-keys/legacy
   - 「Legacy anon, service_role API keys」タブ
   - **anon public** のCopyボタンを押してコピー
8. 「スクリプトプロパティを保存」をクリック

**② スプレッドシートをリロードして動作確認**

1. https://docs.google.com/spreadsheets/d/13fAq0ELCyq8w_bryzt-CEpKrzdDdsPyqYd-UYEqLq6Q/edit を開く
2. メニューバーに「🦝 TASUKARU」が表示される（初回は権限承認が必要）
3. 「🦝 TASUKARU」→「利用者一覧を取得」をクリック
4. 利用者のリストが表示されれば成功！
5. 利用者を選んで「データを入力する」→ シートに自動入力される

**③ 動作確認後にGASコードのカラム位置調整**
- Supabaseのpatientsテーブルのカラム名を確認
- assessmentsテーブルのカラム名を確認
- GASコードのsetValue箇所とシートのセル位置を合わせる

### GASコードの概要（コード.gs）

```javascript
// 設定値
const SUPABASE_URL = 'https://abvglnkwtdeoaazyqwyd.supabase.co';
const FACILITY_CODE = 'cocokaraplus-5526';

// メイン機能
- onOpen() → メニュー追加
- getPatients() → Supabaseから利用者一覧取得
- getAssessment(patientId) → 評価データ取得
- showPatientSelector() → 利用者選択ダイアログ表示
- fillPatientData(patientId) → シートにデータ自動入力
  ├ モニタリング報告書R8.3: G6(氏名), D11(フリガナ), D12(氏名), I11(性別)
  │   J12(生年月日), P12(要介護度), D15-D17(短期目標), D19-D21(長期目標)
  │   B24(変化), L24(課題)
  └ ケース記録R8.3: D3(氏名), D6-D8(短期目標), D9-D11(長期目標)
- openSettings() → APIキー設定画面
- saveSettings(key) → スクリプトプロパティに保存
```

### Supabaseのテーブル構造確認が必要な項目
- `patients` テーブルのカラム：id, user_name, kana, gender, birth_date, care_level
- `assessments` テーブルのカラム：short_function, short_activity, short_participation,
  long_function, long_activity, long_participation, changes, issues
  （カラム名が違う場合はGASコードを修正）

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| sw.js更新で真っ白 | ServiceWorkerキャッシュ競合 | **絶対にバージョンを上げない** |
| 本番mergeでコンフリクト | .DS_Storeの競合 | checkout方式（merge禁止） |
| ベルを押しても反応なし | update-log-modalが存在しない | top.htmlにモーダルHTMLを追加 |
| history-itemクリックで遷移しない | SPA遷移後イベント消える | base.htmlのイベント委譲で管理 |
| GASのメニューが出ない | onOpen未実行 or 権限未承認 | スプレッドシートをリロード→承認 |
| GAS「利用者が見つかりません」 | SUPABASE_KEYが未設定 | スクリプトプロパティを設定 |

---

*最終更新：2026-04-16 夜（GASスプレッドシート連携作業中）*