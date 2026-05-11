# TASUKARU 介護AIアプリ — 開発引き継ぎ(ミニマム版)

> **最新更新: 2026-05-11 Session 33 完了(本番リリース済)**
> このファイルは「次セッションを始める Claude が最初に読むだけで仕事が始められる」ことを目的に**ミニマム化**してある。過去 Session の詳細ログは git history を `git log --all --oneline` で参照する。Session 33 までの累積 README は git の `tasukaru-dev` ブランチ履歴(`README.md` 旧版)に残っている。

---

## 0. 最初に必ず読む3点

1. このREADMEを末尾まで(短いはず)
2. `docs/SESSIONxx_HANDOFF.md` の最新版(直近セッションの引き継ぎ)
3. ユーザーから提示された当回タスクの仕様

---

## 1. プロジェクト基本情報(不変)

### サービス概要
- **TASUKARU**: 介護現場の「書く」負担をゼロにする AI アプリ
- マスコット: タスカルくん(レッサーパンダ/アライグマ風キャラ)
- 介護記録の音声入力、AIによる文章生成、バイタル管理、ケース記録、掲示板、利用者管理など

### 環境
| 環境 | Supabase プロジェクトID | Cloud Run | URL |
|---|---|---|---|
| **本番** | `abvglnkwtdeoaazyqwyd` | `tasukaru` (asia-northeast1) | `https://tasukaru-191764727533.asia-northeast1.run.app` |
| **dev** | `otjevnmoycnvaxeltrtj` | `tasukaru-dev` (asia-northeast1) | `https://tasukaru-dev-191764727533.asia-northeast1.run.app` |

### Git
- リポジトリ: `https://github.com/cocokaraplus-max/kaigo-ai-app`
- **本番ブランチ**: `tasukaru`(`cloudbuild.yaml` で自動デプロイ)
- **dev ブランチ**: `tasukaru-dev`(`cloudbuild-dev.yaml` で自動デプロイ)
- ローカル: `/Users/ZIMAX/.../kaigo-ai-app`(Mac、VSCode ターミナル)

### 施設(本番・dev 共通)
| facility_code | 用途 |
|---|---|
| `cocokaraplus-5526` | 本物の運用施設 |
| `DEMO001` | デモ施設 |
| `YOUR_FACILITY_CODE` | テスト施設 |

---

## 2. 絶対ルール(禁忌・厳守事項)

### 🚨 ブランチ事故防止(教訓 #29)
- ローカル作業中は**常に `tasukaru-dev` ブランチ**。VSCode 左下のブランチ表示を必ず確認
- 本番リリース時のみ `tasukaru` に切り替え、マージ&push したら**即座に `tasukaru-dev` に戻す**
- `git status` で「On branch tasukaru-dev」になっているか毎回確認

### 🚨 本番リリース順序厳守(教訓 #30)
**必ず DB → コード の順**。逆順は本番障害の元。
1. 本番 Supabase で DB 変更(`ALTER TABLE` / `INSERT INTO record_categories` など)
2. DB 変更の確認(SELECT で結果確認)
3. `git checkout tasukaru` → `git merge tasukaru-dev --no-ff` → `git push origin tasukaru`
4. Cloud Build 自動発火、本番デプロイ完了を待つ
5. iPhone で本番動作確認
6. `git checkout tasukaru-dev` でブランチ戻す

### 🚨 Supabase SQL Editor の使い方(教訓 #27)
- 長文 SQL + 日本語コメント + 絵文字を入れると AI 補完が暴走
- **1 文ずつ、短い英字主体の SQL** を実行
- 日本語値を入れる時は値だけ(`'休み連絡'` など)、コメントは別の場所で

### 🚨 CREATE TABLE 時(教訓 #28)
- 緑の「Run」ではなく、**中央に出る薄黄色「Run without RLS」が正解**
- 一度しか出ないので見逃さない

### 🚨 ファイル受領時のハッシュ照合(教訓 #32 新規)
- ユーザーがファイルを添付してきたら、Chrome キャッシュ(`window._xxx`)の SHA-256 と必ず照合
- 一致しなかった場合、ローカルとリモートで差分がある可能性 → そのまま編集すると衝突
- `sha256sum` でハッシュ確認、Chrome 側は `crypto.subtle.digest('SHA-256', ...)` で計算して突合

### 🚨 やってはいけない
- 本番 DB に直接 DROP / TRUNCATE / 大量 DELETE
- 本番ブランチで直接コミット(必ず dev → マージ)
- dev で動作確認していない変更を本番にマージ
- カラム追加なしでコードに新カラム参照を入れる(順序逆転)

---

## 3. 作業の進め方(標準フロー)

### 通常タスク
1. ユーザーから仕様確認(必要なら Q&A 形式で詰める)
2. 影響範囲を grep / 既存コード閲覧で把握
3. dev に対して順に: DB変更 → コード変更 → push → Cloud Build 完了待ち → dev で動作確認
4. dev OK なら本番リリース手順(上記教訓 #30)に進む
5. README 更新 + 次回への SESSION_HANDOFF.md 作成

### ファイル編集の作法
1. ユーザーから VSCode 経由で対象ファイルを `cp ~/Desktop/xxx ./` で受領 → ハッシュ照合
2. Claude 側で str_replace で修正 → `/mnt/user-data/outputs/xxx` に書き出し
3. ユーザーが `present_files` でダウンロード → `cp ~/Desktop/xxx ./` で上書き
4. `git diff` で差分確認 → 想定通りなら add → commit → push

### push 前の最終チェック
- `git status` でブランチが `tasukaru-dev` か(本番作業時のみ `tasukaru`)
- modified が想定ファイルだけか(余計な変更が混ざってないか)
- `git diff | wc -l` で差分量が想定範囲内か

---

## 4. アプリの主要構造(おぼえておきたい)

### カテゴリ管理(2 層構造、重要)
- **`record_categories` テーブル**: 施設ごとに登録、**記録入力画面のカテゴリ選択**で使われる
- **`AIC_MANUAL_CATEGORIES` JS 配列**(`templates/daily_view.html`内ハードコード): **ケース記録の「カテゴリ変更」モーダル**で使われる。DB と独立。
- **`VALID_CATEGORIES` Python set**(`app.py` 内 2 箇所): API 側で受け付ける有効カテゴリのホワイトリスト
- **`AI_CATEGORY_DEFINITIONS` dict**(`utils.py` 内): AI 判定用のカテゴリ定義 + プロンプト
- **検索プルダウン**: `/api/records/search/categories` で `records` テーブル内の実使用カテゴリを動的取得(DB登録と無関係)

→ **カテゴリを増やす時は最低 4 箇所(または 5 箇所)同時更新が必要**。1 箇所でも漏れると挙動が乖離する。

### 現在のカテゴリ(Session 33 完了時点)
9 カテゴリ: 入浴 / 食事 / 排泄 / コミュニケーション / 心身状況 / 訓練状況 / ヒヤリハット / 休み連絡 / その他
- 「休み連絡」は Session 33 で追加。`leave_reporter_type` (self/family) と `leave_reporter_relation` (任意の文字列) を持つ
- ヒヤリハットは `cocokaraplus-5526` にも今回追加した(dev にはまだ未追加、次セッションで dev 反映が必要)

### Cloud Build トリガー
- `tasukaru` ブランチ push → `cloudbuild.yaml` 走行 → `tasukaru` Cloud Run
- `tasukaru-dev` ブランチ push → `cloudbuild-dev.yaml` 走行 → `tasukaru-dev` Cloud Run
- 平均 2〜5 分でデプロイ完了

### Chrome タブ構成(セッション開始時にあると便利)
- dev アプリ(daily_view または top)
- 本番アプリ(top)
- 本番 Cloud Logs
- 本番 Cloud Build
- dev Supabase SQL Editor
- 本番 Supabase SQL Editor

---

## 5. 教訓集(累積)

| # | 内容 |
|---|---|
| #27 | Supabase SQL Editor は長文+日本語コメントで AI 補完暴走 → 1 文ずつ短い英字主体 |
| #28 | CREATE TABLE 時は中央薄黄色「Run without RLS」が正解(緑ではない) |
| #29 | VSCode 左下ブランチは常に `tasukaru-dev`(本番作業時のみ一時的に `tasukaru`、終わり次第戻す) |
| #30 | 本番リリースは DB → コード の順序厳守 |
| #31 | daily_view のカテゴリ変更モーダルは JS ハードコード(`AIC_MANUAL_CATEGORIES`)、DB の `record_categories` とは別世界(Session 33) |
| #32 | ファイル受領時は SHA-256 で必ずハッシュ照合(Chrome キャッシュ vs 添付ファイル)。整合性確認なしに編集進めない(Session 33) |
| #33 | カテゴリ追加は最低 4-5 箇所同時更新が必要: `record_categories` テーブル / `AIC_MANUAL_CATEGORIES` 配列 / `VALID_CATEGORIES` set 2 箇所 / `AI_CATEGORY_DEFINITIONS` dict(Session 33) |

---

## 6. 直近セッションのサマリ(過去 2-3 件だけ)

### Session 33(2026-05-11)完了 — 休み連絡カテゴリ追加 + タスカルくん歩行
**本番リリース commit**: `b8529b9`
- 新カテゴリ「休み連絡」を全 3 施設に追加(色: `#EC4899`)
- `records` テーブルに `leave_reporter_type` (text/null) + `leave_reporter_relation` (text/null) カラム追加
- 記録入力画面に休み連絡用フォーム(本人/家族 + 関係性)
- ケース記録カードに「○○より連絡」ピンクバッジ
- 編集 UI で誰から/関係性を後から修正可能
- カテゴリ変更ローディングを**タスカルくんシルエット歩行アニメ**に置き換え(`tasukaruカラー.png` を `filter: brightness(0) opacity(0.5)` でシルエット化)
- AI カテゴリ判定が「休み連絡」も対象に(「誰から」までは AI に推測させない設計)
- ついでに `cocokaraplus-5526` にヒヤリハットも追加(色: `#EF4444`、dev は未対応 → 次セッションで反映)

### Session 32(2026-05-11)完了 — 掲示板分離 + ケース記録閲覧改善
**本番リリース commit**: `4df54ad`
- 掲示板の「確認」と「リアクション」を完全分離(`board_checks` テーブル新設、207 件移行)
- 確認/未確認ボタンの数字バッジ削除、緑✅Nチップ削除
- 下メニューの未読バッジを掲示板ページでも表示
- ケース記録の利用者アコーディオン展開で自動既読化+カウント+1
- AI 統合記録の一時非表示機能

### Session 31(2026-05-10)完了 — AI カテゴリ自動振り分け
- AI が記録本文を読んで 8 カテゴリ(当時)に自動分類
- 管理者 MENU の「AI 自動カテゴリ判定」機能(一括判定+適用+巻き戻し)
- 個別記録のカテゴリ変更モーダル(`AIC_MANUAL_CATEGORIES` 配列)
- カテゴリピッカー UI(記録入力画面)

---

## 7. 既知の未対応事項(次セッションでの対応候補)

- **dev の `cocokaraplus-5526` にヒヤリハットがまだ無い** → 本番と揃えるため次セッションで追加(DB操作のみ)
- 旧 README(累積版、4216 行)が git history に残っている。完全に消すか、`docs/README_ARCHIVE.md` として保存するか判断が必要
- 休み連絡カテゴリの AI 判定精度を実運用で観察(low confidence で「その他」に倒れる頻度確認)

---

## 8. 次セッション開始の標準シーケンス

```bash
# ローカルの状態確認
cd /Users/ZIMAX/.../kaigo-ai-app
git status                                # On branch tasukaru-dev であること
git pull origin tasukaru-dev              # 最新を取得
git log --oneline -5                      # 直近 5 commit を確認

# Chrome タブを開く(可能なら)
# - dev daily_view, 本番 top, 本番 Cloud Build, dev Supabase, 本番 Supabase

# このREADMEと SESSION34_HANDOFF.md を Claude に提示
```

---

以上。これだけ読めば次セッションを始められる。詳細は git history + Supabase Dashboard で確認可能。
