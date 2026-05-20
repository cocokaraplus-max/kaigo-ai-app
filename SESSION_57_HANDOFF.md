# TASUKARU 開発引き継ぎ — Session 57

---

## チャット冒頭に貼る文章

```
あなたはTASUKARUという介護記録システムの開発パートナーです。
前のClaudeと同じレベルで作業を続けてください。

【作業スタイルの引き継ぎ】
1. 変更前に必ず現在のコードを確認してから修正する
2. Pythonスクリプトは /mnt/user-data/outputs/ に作成してpresent_filesでダウンロードさせる方式
3. 必ずdev（tasukaru-dev）で確認→本番（tasukaru）マージの順番を守る
4. 日本語テキストはすべてUnicode（\uXXXX）エスケープで記述する
5. デプロイはgit push origin tasukaru-devだけでOK（約2〜3分）
6. vitals.htmlは大きなファイル（4100行超）のためデプロイに3分程度かかる
7. Chrome連携ツールでdev環境の動作確認ができる
8. Service Workerキャッシュ問題が多いため確認前に navigator.serviceWorker.getRegistrations().then(r=>r.forEach(sw=>sw.unregister())) を実行する

【プロジェクト情報】
リポジトリ: cocokaraplus-max/kaigo-ai-app
ローカル: /Users/ZIMAX 1/dev/kaigo-ai-app/
ブランチ: 開発=tasukaru-dev / 本番=tasukaru
dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
本番URL: https://tasukaru-191764727533.asia-northeast1.run.app
本番Supabase: abvglnkwtdeoaazyqwyd (facility_code: cocokaraplus-5526)
dev Supabase: otjevnmoycnvaxeltrtj (facility_code: DEMO001)
技術スタック: Python/Flask, Supabase, Cloud Run, Jinja2テンプレート
GEMINI_API_KEY: Cloud Runに設定済み（dev・本番両方）
ANTHROPIC_API_KEY: Cloud Runに設定済み（dev・本番両方）

Session 57の引き継ぎファイルを読んで、残タスクから作業を開始してください。
引き継ぎファイル: /Users/ZIMAX 1/dev/kaigo-ai-app/SESSION_57_HANDOFF.md
```

---

## Session 56 完了済み作業（devのみ・本番未マージ）

### 最新commitログ（tasukaru-dev）
- 4fa22fa: fix: use String() comparison for event id to prevent duplicate on edit
- 3236f88: fix: expose pauseBulkTempVoice to window scope
- 33aeb47: fix: update recording start to use new rec-bar UI, remove countdown timer
- 7da26f4: feat: add pause/resume to bulk temp, remove timer and memo pad
- c178fca: chore: remove backup files
- 7295fa9: fix: directly call initMemoResize in toggleMemoPad
- 25a3fbd: feat: show order in bulk temp button label and add confirm dialog
- 7b49426: fix: change bulk-stop-btn from div to button for iOS tap support
- a1db60c: fix: auto-expand vital card before setting bulk temp value
- aff8f92: design: update bulk temp UI to plan A
- 6e84ae3: fix: expose voice helper funcs to window to fix IIFE scope issue
- 260d561: ← 本番(tasukaru)はここまで反映済み

---

## 残タスク

### 優先度：最高
1. **本番マージ**（動作確認後）
```bash
cd "/Users/ZIMAX 1/dev/kaigo-ai-app" && git checkout tasukaru && git merge tasukaru-dev && git push origin tasukaru && git checkout tasukaru-dev
```

2. **カレンダー重複バグの動作確認**
- 休み連絡を記録入力で登録→カレンダーに自動追加
- カレンダーからイベント日付を変更
- 元の日付のスケジュールが消えて新しい日付に1つだけ表示されるか確認
- 修正内容: calendar.htmlのString()比較でid型不一致を解消

3. **体温一括入力 一時停止の動作確認（iPhone実機）**
- iPhoneでSafariキャッシュ消去後に確認
- 録音→一時停止→再開→停止・解析→体温フィールドに入力されるか

---

## 重要な技術的知見（Session 56で判明）

### vitals.htmlのスクリプト構造
- ブロック[4]（約15万文字）がメインスクリプトで(function(){...})()でIIFEラップ
- IIFE内の関数は外から参照できないため window.xxx = function で公開必要
- 公開済み: pickVoiceMime, mimeToExt, cleanupBulkTempStream, cleanupMemoVoiceStream,
  stopBulkTempVoice, sendBulkTempVoice, sendMemoVoice, pauseBulkTempVoice,
  updateBulkTempLabel

### 体温一括入力のUI構造（Session 56最終版）
- 録音前: #bulk-temp-btn（フルワイドオレンジボタン）表示
- 録音中: #bulk-rec-bar（録音中バー）表示、bulk-temp-btnは非表示
  - #bulk-pause-btn: 一時停止/再開ボタン
  - #bulk-stop-btn: 停止・解析ボタン（赤）
- 30秒タイマー・カウントダウン削除済み（無制限録音）
- 一時停止: MediaRecorder.pause()/resume() 使用
- iOS SafariはMediaRecorder.pause()非対応→Chrome/Android限定機能

### カレンダー・休み連絡連携
- 記録入力で「休み連絡」カテゴリ → calendar_eventsに自動登録
- records.calendar_event_idでリンク
- カレンダーからイベント編集 → api_save_calendar_event → recordsも更新
- バグ修正: editingEventIdがstring、ALL_EVENTSのidがnumberで型不一致
  → String()変換で統一

### Service Workerキャッシュ問題
- CACHE_VERSION: tasukaru-v8
- Chromeで古いJSが読まれる場合: DevToolsで SW登録解除が有効
  navigator.serviceWorker.getRegistrations().then(r=>r.forEach(sw=>sw.unregister()))
- iPhoneは設定→Safari→履歴とWebサイトデータを消去

### スクリプト作成方法
- ターミナルのヒアドキュメント（cat << 'EOF'）は文字化けするため使用禁止
- /mnt/user-data/outputs/にファイル作成→present_files→ダウンロード→実行
