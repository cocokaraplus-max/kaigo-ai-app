# SESSION 61 HANDOFF — LINE連携（受信側完成・送信側が次）

作成: 2026-06-22 / ブランチ: tasukaru-dev / 全てDEV止まり・**本番未反映**

## このセッションでやったこと（DEV完成・実機確認済み）

LINE連携の「受信側」を一通り完成させた。施設別トークン方式（SaaS対応・施設ごとに別LINE公式アカウント＋別トークン、データ完全分断）。

1. **施設のLINE設定画面**（`line-settings-ui-v1`）: admin.html「AIカテゴリ自動振り分け」直前に「LINE連携設定」box。トークン/シークレットはFernet暗号化保存・画面はマスク表示（値は返さない）。管理者限定。
2. **Webhook**（`line-webhook-v1`）: `POST /line/webhook/<facility_code>`（公開）。施設判別はURLのfacility_code。署名検証は `get_line_settings` の復号済み `channel_secret` でHMAC-SHA256（生ボディ）。follow/messageでuserIdを `line_friends` に未紐付け保存。
3. **display_name取得**（`line-profile-v1`）: `_line_get_profile()`（施設トークンで `GET /v2/bot/profile/{userId}`、タイムアウト3秒・失敗時None・保存を妨げない）。
4. **友だち管理＝手動紐付け**（`line-friends-api-v1` / `line-friends-ui-v1`）: 一覧/link/unlink API（管理者限定・二条件guard・利用者存在検証）。UIは検索窓（名前/かな/Noでインクリメンタル検索）＋確認ダイアログ（誰に何が届くか明示）＋解除。

道中、起動失敗を2件解決:
- `NameError: login_required`（`line-api-move-v1`）: LINE設定APIがlogin_required定義より前にあった→定義後へ移動。
- endpoint名衝突（`line-webhook-legacy-rename-v1`）: 旧 `line_webhook()` と新 `line_webhook(facility_code)` の関数名衝突→旧を `line_webhook_legacy` にリネーム。
- **教訓**: `py_compile` は起動時エラー（NameError/endpoint衝突）を検出しない。push前に `SECRET_KEY=dummy python3 -c "import app"` でimportが通るか確認すること。

## DDL（DEVのSupabaseに適用済み）

```sql
create table if not exists line_friends (
  id uuid primary key default gen_random_uuid(),
  facility_code text not null,
  line_user_id text not null,
  display_name text,
  patient_id uuid,
  status text not null default 'unlinked',
  linked_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (facility_code, line_user_id)
);
create index if not exists idx_line_friends_fac on line_friends (facility_code, status);
```

## 実機テスト環境（DEV）

- テスト施設: DEMO001
- テスト用LINE公式アカウント: 「【公式】ココプラスタッフ用」(@145tminp)、Channel ID 2010464312、プロバイダー TASUKARU。**本番の家族用アカウントとは別**。
- Webhook URL（LINE Developers登録済み）: `https://tasukaru-dev-191764727533.asia-northeast1.run.app/line/webhook/DEMO001`
- DEMO001のline_settingsにトークン/シークレット登録済み・有効ON。
- 実機確認済み: 友だち追加→unlinked保存→display_name取得→青木利夫（patient_id=5c0f9541-3c6b-4710-98f9-f7b2a3406655）に手動紐付け→status=linked。

## 次にやること（送信側）

**設計の絶対ルール: linked の友だちにしか送信しない。** unlinkedには絶対送らない（誤送信=個人情報漏洩を構造的に防ぐ）。

1. **連絡帳のLINE向け整形**: 行った場所・食事量を箇条書き、連絡事項は家族向け文章、血圧グラフは**PNG画像**で送る（LINEは公式アカウントからのPDF送信に非対応）。連絡帳印刷（renraku_print.html）のSVGロジックが流用候補だが、LINEはPNG必要なのでサーバー側で画像化する手段の検討が要る。
2. **送信プレビュー編集UI → 送信API**: プッシュメッセージ（1回最大3吹き出し=1通）。送信先は「その利用者にlinkedな全userId」。送信前にプレビュー編集。料金=送信回数×友だち数（プッシュ/マルチキャスト/ブロードキャストが課金、リプライは対象外）。
3. （低優先）合言葉による自動紐付け。採用するなら誤紐付け対策（コード1回限り等）必須。HIROの判断では**当面は手動主軸で見送り**。

## 運用メモ

- 本番の家族用アカウントは日常的に手動チャット運用中。応答モードは「チャット」のままWebhook有効化で手動チャットとAPI送信は共存可能。
- 料金プラン: コミュニケーション(0円/月200通)・ライト(5,000円/月5,000通)・スタンダード(15,000円)。
- LINE関連の新ルートは `line-api-move-v1` ブロック（login_required定義後）付近に追加すること（ファイル前方に@login_required付きルートを置くと起動失敗）。

## 主なマーカー / コミット（tasukaru-dev）

- `a30d402` LINE設定UI / `c36fa96` 起動NameError修正 / `e8c6c32` Webhook+旧リネーム+README§26 / `3fba279` display_name / 友だち管理API+UI
- markers: line-settings-ui-v1, line-api-move-v1, line-webhook-v1, line-webhook-legacy-rename-v1, line-profile-v1, line-friends-api-v1, line-friends-ui-v1
- README: §26（起動エラー修正）, §27（Webhook〜友だち管理）まで記録済み。
