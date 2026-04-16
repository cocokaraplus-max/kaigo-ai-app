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
> ダウンロードしたファイルが古いことが多い。
> 確実な方法：VS Codeでファイルを直接開いてコードを貼り付ける。
> Claudeはコード変更があれば完成版ファイル全体を出力して、VS Codeに貼り付けてもらう。
>
> **⚠️ sw.jsは絶対に触らない**
> バージョンを上げると真っ白になる。現在：tasukaru-v4（固定）

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

## 開発者の意図・哲学

1. **タスカルくん（🦝）を大切に** → マスコット。変更不可
2. **スマホファースト** → iPhoneで快適に動くことが必須
3. **iPhoneの操作感** → ナビ並び替えはiPhoneのホーム画面のようなプルプル震える操作感
4. **エラーはゼロが目標** → Chrome連携でコンソールエラーを確認してからデプロイ
5. **シンプル** → 機能を増やすより使いやすさを優先

---

## 開発ルール

1. `patients.id`はbigint型 → patient_idはTEXT型で持つ
2. 環境変数更新は`--update-env-vars`のみ（`--set-env-vars`は厳禁）
3. スクリプトはすべてIIFEで囲む
4. 全関数を`window.xxx`で公開する
5. 開発はcloudrun-devで行い、確認後にcloudrunにマージ
6. **sw.jsのバージョンは絶対に上げない** → 真っ白になる
7. `position:fixed`の要素はpage-wrapperの外に置く（iOSのoverflow制約）
8. HTMLの構造修正は必ずPythonスクリプトで行う（VS Codeの貼り付けは構造が壊れやすい）

---

## デプロイコマンド

```bash
# 開発版
git add . && git commit -m "変更内容" && git push origin cloudrun-dev
gcloud run deploy tasukaru-dev --source . --region asia-northeast1 --platform managed --allow-unauthenticated

# 本番同期
git stash && git checkout cloudrun && git merge cloudrun-dev && git push origin cloudrun
gcloud run deploy tasukaru --source . --region asia-northeast1 --platform managed --allow-unauthenticated
git checkout cloudrun-dev && git stash pop
```

---

## 2026-04-16 大規模作業記録

### ✅ 完了

1. **本番の記録保存エラー緊急修正**
   - app.pyのinput_viewにXHRヘッダー判定追加（本番のapp.py 587行目付近）
   - `if request.headers.get("X-Requested-With") == "XMLHttpRequest":` でJSON返却
   - **develop(cloudrun-dev)のapp.pyにはまだ未適用 → 要対応**

2. **マニュアル Ver.4.0**（本番適用済み）
   - カラータスカルくん・タスクセクション・カスタマイズセクション・更新ログ追加

3. **歯車・ベルボタン**
   - base.htmlにCSS/HTML/JS移植完了
   - ベル🔔と歯車⚙️が右上に並んで表示される

4. **設定モーダル**
   - base.htmlに移植完了（全ページで動作）
   - top.htmlから削除済み
   - 開くと「ユーザー設定」タイトル・文字サイズ・通知サウンド・並び替えボタンが表示される

5. **ナビ並び替え機能**
   - top.htmlにstartNavEditMode/stopNavEditModeを追加
   - 「並び替えモードを開始」→完了バーが動作確認済み
   - Chrome上でも動作確認済み

### ❌ 残っている問題（次のClaudeが対応）

**最優先1：メニュー表示モード（2段/横スクロール切り替え）を削除**

開発者の意向：2段モードは削除してシンプルに横スクロール1本にする。

base.htmlから以下を削除する：
- `<!-- メニュー表示モード -->` セクションのHTML（nav-mode-btnボタン2つ）
- CSS の `.nav-mode-btn` / `.bottom-nav.two-row` 関連
- JS の `applyNavMode` 内のtwo-row処理
- JS の `.nav-mode-btn` クリックイベント処理

**最優先2：develop版のapp.pyに記録保存修正を適用**

```bash
cd "/Users/ZIMAX 1/Desktop/kaigo-ai-app"
# cloudrun-devブランチで実行
sed -i '' 's/return redirect(url_for("daily_view", user=user_name, date=record_date_str))/if request.headers.get("X-Requested-With") == "XMLHttpRequest":\n                        return jsonify({"status": "success", "redirect": url_for("daily_view", user=user_name, date=record_date_str)})\n                    return redirect(url_for("daily_view", user=user_name, date=record_date_str))/' app.py
grep -c "X-Requested-With" app.py  # 1以上になればOK
```

**その他：**
- スマホでの動作確認（プルプルアニメ・ドラッグ・ベル）
- develop版manual.htmlをカラータスカルくん版に更新

---

## base.htmlの現在の構造（重要）

```
【CSS（~200行目）】
- .page-wrapper
- .settings-fab / .top-fab-area
- .nav-edit-bar / .nav-edit-bar.show / .nav-edit-bar-done
- .settings-modal / .settings-sheet / .settings-title等
- .sound-opt / .sound-opt.active
- .font-slider等
- ★.nav-mode-btn / .bottom-nav.two-row ← 削除予定

【HTML】
325行目: <div class="nav-edit-bar" id="nav-edit-bar">
345行目: <div class="settings-modal" id="user-settings-modal">
         - 文字サイズスライダー
         - 通知サウンド（ポップ/チャイム/ピコン/タスカル/なし）
         - ★メニュー表示モード（横スクロール/2段） ← 削除予定
         - メニュー並び順「並び替えモードを開始」ボタン ← 残す
         </div>
381行目: <div class="top-fab-area">（ベル・歯車ボタン）
391行目: <div class="page-wrapper">

【JS（グローバルスコープ）】
- saveNavOrder(order)
- showToastMsg(msg)
- hideBottomNav() / showBottomNav()
- window.openSettings() / window.closeSettings()
- applyNavMode() / applyNavOrder()
- ★applyNavModeUI() ← この関数が未定義の可能性あり

【document.addEventListener（イベント委譲）】
- #update-log-btn → 更新ログモーダルを開く
- #settings-fab-btn → openSettings()
- #settings-close-btn → closeSettings()
- #start-nav-edit-btn → startNavEditMode()（stopPropagation済み）
- #nav-edit-done-btn → stopNavEditMode()
- .sound-opt → サウンド選択
- ★.nav-mode-btn → ナビモード切替 ← 削除予定
- .preview-btn → 試聴
- font-slider → フォントサイズ変更
```

---

## top.htmlの現在の状態

- 719行のベース + VS Codeで以下を追加
- IIFE の先頭付近に追加：
  - `window.startNavEditMode` / `window.stopNavEditMode`
  - `onNavItemTouchStart` / `onNavItemTouchMove` / `onNavItemTouchEnd`
  - `onNavItemMouseDown`
- 設定モーダルHTMLは削除済み
- 設定モーダルのCSSはtop.htmlに残っているが無害

---

## Supabaseテーブル

- `records`：`record_date`カラムは存在しない（insertに含めると失敗）
- `tasks` / `task_projects`：タスクリスト機能
- `_tasukaru_deploy`：開発用一時保存（nav_code_b64等）

---

## タスカルくん画像

```
/static/tasukaruカラー.png        カラー版（メイン・マニュアルヘッダーに使用）
/static/tasukaru_sestumei.png     説明・案内（白黒）
/static/tasukaru_odoroki.png      驚き（白黒）
/static/tasukaru_ooyorokobi.png   大喜び（白黒）
/static/tasukaru_onegai.png       お願い（白黒）
```

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| sw.js更新で真っ白 | ServiceWorkerキャッシュ競合 | **絶対にバージョンを上げない** |
| パスのスペースでcp失敗 | `ZIMAX 1`のスペース | `"/Users/ZIMAX 1/..."` でクォート |
| ヒアドキュメントSyntaxError | シングルクォート衝突 | VS Codeで直接貼り付け |
| page-wrapperのwidth/height:0 | 設定モーダルHTMLが構造破壊 | Pythonで正確に書き直す |
| 500エラー | Jinja2テンプレート構造破壊 | `git revert HEAD`で戻す |
| openSettingsがundefined | IIFEに閉じ込められている | `window.openSettings`で公開 |
| ボタンが押せない（iOS） | page-wrapper内にposition:fixed | base.htmlのpage-wrapper外に移動 |
| ダウンロードファイルが古い | キャッシュ問題 | VS Codeで直接貼り付けが確実 |

---

*最終更新：2026-04-16 深夜（Ver.4.0 長期作業セッション）*