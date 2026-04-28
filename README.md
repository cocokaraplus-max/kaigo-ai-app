# TASUKARU (介護AI支援アプリ)

## 概要
介護施設向けの記録・管理システム

## 最新状況 (2026-04-28)

### Phase 12 カレンダーバー連結機能 完成 ✅
- **commit**: `1c7919f` 
- **機能**: 複数日イベントのセル境界を完全に隠す連続表示
- **追加**: 隣月セルへのバー延長、タッチスワイプ月切り替え
- **技術**: MutationObserver による自動再描画対応

### 完了済み機能履歴
- `09c17ca` 複数日イベントの期間バー描画(サーバー側実装) 
- `d3abe0c` Phase 11: モーダル透明度改善
- `7b0322d` Phase 10: モーダル z-index 向上
- 予定の追加・編集・削除
- カレンダーの新規作成・編集・削除
- iPhone PWA モーダル残留バグ修正

## ブランチ構成
- `tasukaru` (本番) → Cloud Run "tasukaru" → 本番Supabase
- `tasukaru-dev` (開発) → Cloud Run "tasukaru-dev" → dev Supabase
- `main`

## URL
- 本番: https://tasukaru-191764727533.asia-northeast1.run.app
- dev: https://tasukaru-dev-191764727533.asia-northeast1.run.app

## 技術スタック
- Flask (Python)
- Supabase (PostgreSQL)
- Google Cloud Run
- PWA対応

## 開発環境
- Mac ローカル開発 (VS Code + ターミナル)
- 作業フォルダ: ~/dev/kaigo-ai-app
- GitHub: cocokaraplus-max/kaigo-ai-app