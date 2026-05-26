# TASUKARU 開発引き継ぎ - Session 58

## プロジェクト基本情報
- リポジトリ: cocokaraplus-max/kaigo-ai-app
- ローカル: /Users/ZIMAX 1/dev/kaigo-ai-app/
- dev URL: https://tasukaru-dev-191764727533.asia-northeast1.run.app
- prod URL: https://tasukaru-191764727533.asia-northeast1.run.app
- dev Supabase: otjevnmoycnvaxeltrtj (DEMO001)
- prod Supabase: abvglnkwtdeoaazyqwyd (cocokaraplus-5526)
- 開発ブランチ: tasukaru-dev -> 本番: tasukaru

## 重要ルール
1. 日本語を含むヒアドキュメント(<< 'EOF')は使わない
2. Pythonスクリプトはファイル作成->ダウンロード->実行
3. devでテスト->本番マージの順序を守る
4. PRODのDBは現場使用中->テストはDEVのみ
5. APIキーはスクリプト内にベタ書きしない

## Session 58で完了した実装

### ケース記録
- カレンダーに写真ありオレンジドット+凡例表示
- カレンダースワイプで月変更
- 利用者名横に写真ありオレンジ丸
- 二重ドットバグ修正

### バイタル
- 体温一括測定の誤マッチング修正(プロンプト強化+登録外名前フィルタ)
- 体温一括測定後の測定欄自動入力削除
- 体温登録後リロード処理追加
- bulk_temp_smart_saveのロジック修正(最古の空欄レコードに入れる)

### 評価ページ
- セクション名「記録と課題・訓練による変化と課題」に変更(2行表示)
- AI生成ボタンを常時表示
- 文字数選択(100/200/300/400/500文字)追加
- プロンプト強化(両項目必須生成・ハルシネーション防止)

### その他
- Ver.4.3更新履歴追加

## 次のTODO(最優先)

### 1. 書類出力ページ新規作成
実物の印刷サンプル(IMG_4852.JPG)を参考にA4レイアウトで作成。

#### ページ構成
- 利用者選択 + 期間選択
- 印刷項目トグル選択
  - モニタリング: 心身状況/訓練状況/コミュニケーション等
  - 評価: 訓練による変化/課題とその要因/特記事項等
  - 体力測定: 体重/握力/TUG等グラフ
- プレビュー表示(A4想定)
- 印刷・PDF保存

#### 使用テーブル
- monitoring_reports: full_text, categories(心身状況・訓練状況等)
- patient_evaluations: changes_by_training, issues_and_causes, special_notes,
  satisfaction, service_appropriateness, new_requests_exist/detail
- body_weights: weight_kg, measured_date
- fitness_tests: grip_right/left, tug_sec, sit_stand_30sec等

#### 印刷レイアウト(実物参考)
- ヘッダー: ケアプランセンター名・施設情報・利用者名・要介護度・作成担当者・作成日
- 短期目標・長期目標(機能/活動/参加 x 継続/達成/未達成)
- 個別機能訓練実施による変化(左) + 課題とその要因(右) 2カラム
- モニタリング表(心身状況・訓練状況・コミュニケーション)
- 体力測定推移グラフ(直近6ヶ月)
- 特記事項・新しい希望・満足度・サービス適切か

#### モニタリング・評価ページの変更
- 印刷・PDFボタンを削除
- 「保存して書類出力へ」ボタンに置き換え

#### ナビ
- ボトムナビに「書類出力」を追加(並び替え対象)

### 2. 残りTODO
- Stripe Webhookの動作確認
- 契約期限通知システム(Cloud Scheduler)
- ガイドページ更新(体温一括測定)
- バイタルAI判断機能(運動可否判断)
  - 絶対基準(施設設定) + 個人基準(過去データから自動判断)
  - Geminiが「運動推奨/軽運動/安静」を判断
  - ボタン押下時のみ判断表示

## コード場所メモ
- monitoring_reports保存API: app.py L5628
- patient_evaluations: app.py L5573
- body_weights/fitness_tests取得: app.py L8510
- ai_fill API: app.py L3785
- bulk_temp_smart_save: app.py L2484
- vital_bulk_temp: app.py L8723
- カレンダードット: templates/daily_view.html L1940付近
- 書類出力ページ: 未作成(新規)

## DBテーブル構造メモ(書類出力用)
monitoring_reports:
  facility_code, user_name, target_month, mode, categories(JSON),
  full_text, record_counts, confirmed_at, confirmed_by

patient_evaluations:
  facility_code, user_name, year_month,
  changes_by_training, issues_and_causes, special_notes,
  satisfaction, service_appropriateness,
  new_requests_exist, new_requests_detail

body_weights:
  facility_code, patient_id, measured_date, weight_kg, note

fitness_tests:
  facility_code, patient_id, measured_date,
  grip_right, grip_left, standing_balance_sec,
  tug_sec, walk_5m_sec, sit_stand_30sec, note
