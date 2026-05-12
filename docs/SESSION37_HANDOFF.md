# SESSION 37 ハンドオフ書

> **前 Session: 36 / 作成: 2026-05-13 / 担当: ZIMAX + Claude**
> このハンドオフ書を最初に読んで、現状確認から始めること(教訓 #38)。

---

## 🎯 Session 36 の成果(本番リリース済み)

**Phase 2.A: VAS 入力機能 — 完成・本番リリース完了 ✅**

介護現場の介護者が iPhone で以下が可能に:
- カテゴリ「心身状況」「訓練状況」を選ぶと VAS ウィジェット表示
- 人体図(54 部位、正面 31 + 背面 23)をタップ → 0〜10 NRS で入力
- 部位ごとの値が赤色グラデーション(冷淡→赤系)でハイライト
- ケース記録画面で赤色 VAS リスト表示(部位ラベルは日本語に自動変換)
- 編集モードから VAS 編集モーダル → 値変更・部位追加・部位削除

本番動作確認(iPhone)済み。安定運用中。

---

## ⚠️ 最初にやること(教訓 #38)

ハンドオフ書を盲信せず、現実を確認してから着手すること。

### 1. ブランチ確認(教訓 #29)

```bash
cd "/Users/ZIMAX 1/dev/kaigo-ai-app"
git status
git branch --show-current
git log --oneline -10
```

期待:
- ブランチ: `tasukaru-dev`
- 直近コミット先頭: `96f836b fix(vas): iPhone-friendly VAS edit modal (sticky bottom action buttons)`
- 続いて `d89406d` `24d9aef` `56cf5dc` `77bcae9` `cb25d97`(全部 Session 36 のコミット)

### 2. DB 状態確認

```sql
-- dev・本番両方の Supabase で実行(両方とも結果は同じはず)
SELECT table_schema, table_name FROM information_schema.tables WHERE table_name = 'record_vas';
```
期待: `public, record_vas` の 1 行(dev・本番両方適用済み)

```sql
SELECT table_schema, table_name FROM information_schema.tables WHERE table_name = 'patient_evaluations';
```
期待: **0 行**(dev・本番ともに未作成。Phase 2.B 着手時に作る)

### 3. 設計ドキュメント存在確認

```bash
ls -la docs/CARE_MANAGER_REPORT_DESIGN.md
shasum -a 256 docs/CARE_MANAGER_REPORT_DESIGN.md
```

期待ハッシュ: `e578dc81812b59bea99471748b7a2152b9b0ed37bdfb924390a0f77e776135ff`

### 4. dev で実際に動かして確認

dev URL `https://tasukaru-dev-191764727533.asia-northeast1.run.app/daily_view` を開く →
「池田 ヨシ」記録 (record_id=5097) に**赤色 VAS 表示**「胸部 7、上背部 5」が見えること。

---

## 📋 Session 36 の成果詳細

### コミット履歴

```
96f836b fix(vas): iPhone-friendly VAS edit modal (sticky bottom action buttons)
d89406d feat(vas): display + edit VAS records in daily_view (Session 36 Step 6)
24d9aef fix(vas): include vas_records in saveRecord FormData
56cf5dc feat(vas): persist VAS records + collapsible accordion UI (Session 36 Phase 2.A)
77bcae9 fix(vas): modal hidden attribute now respected (was overridden by display:flex)
cb25d97 feat(vas): add VAS widget for 心身状況/訓練状況 (Session 36 Phase 2.A WIP)
```

本番マージ: `4487148 Merge branch 'tasukaru-dev' into tasukaru`(`bb7e681..4487148`)

### 主要ファイルと最終ハッシュ

| ファイル | 行数 | ハッシュ |
|---|---|---|
| `app.py` | 5827 | `0ebb681050636f7db839c82480d1d333d5a5c7e793a37a423851060d89996d9d` |
| `templates/_vas_widget.html` | 852 | `51d4008390c4e7d7d73c4ba31868493cb5f1f7da916d9610e18f999c95105eee` |
| `templates/daily_view.html` | 3056 | `3207fab653f8c6fcbcadfd08ea2df794bde874b4756379c89d405e49c88af01a` |
| `static/img/body/body_front.png` | バイナリ | `43116441872c98b170765e7f3990b8f3b511f65cddd4fd088f590d11b140490d` |
| `static/img/body/body_back.png` | バイナリ | `d12b96d9a0d581d614e4db61d04056263f212305f5738cfce16fa3e83f52cd69` |

### DB 状態(dev・本番両方)

**`record_vas` テーブル**(両環境とも適用済み):

```sql
CREATE TABLE public.record_vas (
    id              BIGSERIAL PRIMARY KEY,
    record_id       BIGINT NOT NULL REFERENCES public.records(id) ON DELETE CASCADE,
    facility_code   TEXT NOT NULL,
    user_name       TEXT NOT NULL,
    part            TEXT NOT NULL,
    side            TEXT NOT NULL CHECK (side IN ('l', 'r', 'center')),
    vas_value       SMALLINT NOT NULL CHECK (vas_value >= 0 AND vas_value <= 10),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_record_vas_record_id      ON public.record_vas(record_id);
CREATE INDEX idx_record_vas_facility_user  ON public.record_vas(facility_code, user_name);
```

**`patient_evaluations` テーブル**:dev・本番ともに**未作成**。Phase 2.B 着手時に作成(教訓 #30: DB → コード順)。
Session 35 のハンドオフ書には「dev 適用済み」と書かれていたが、これは誤情報だった(教訓 #45 案件)。

### 解決したバグ 3 件

1. **モーダル開きっぱなし**(commit `77bcae9`)
   - 原因: CSS `.vas-modal { display: flex }` が HTML `hidden` 属性を上書き
   - 修正: `.vas-modal:not([hidden]) { display: flex }` セレクタに変更
   - 教訓 #42

2. **VAS データ 0 件問題**(commit `24d9aef`)
   - 原因: `input.html` `saveRecord()` の手動構築 FormData に `vas_records` の append が漏れていた
   - hidden input には正しい JSON が入っていたが、フォーム送信時に送られていなかった
   - 検出: Chrome MCP `javascript_tool` で `saveRecord.toString()` を確認、`appendCount: 10` から漏れ判明
   - 修正: line 553 に 1 行 `formData.append('vas_records', ...)` 追加
   - 教訓 #44

3. **iPhone でモーダル確定ボタン押せない**(commit `96f836b`)
   - 原因: iPhone 下端タブ + Safari ホームバーで「キャンセル」「この内容で確定」が隠れる
   - 修正: モーダル `align-items: flex-start`、`margin-bottom: 80px`、アクションボタン `position: sticky; bottom: 0`、`min-height: 44px`
   - 教訓 #43

---

## 📝 Session 36 で発動した教訓(#39〜#45)

### #39 — 左右 ID 付与は本人視点(医療慣習)
左右別がある部位(`_l` / `_r`)は**本人視点**で命名すること。画面座標で `_l` を画面左にすると医療職と齟齬が出る。

### #40 — SVG ドラッグ UI で pointerdown 直後の再描画禁止
`pointerdown` イベントの中で要素の DOM を再生成すると、ブラウザの pointer capture が切れてドラッグが続かない。状態だけ変えて、再描画は `pointerup` まで遅延する。

### #41 — 設計時の部位リストは「臨床的に意味のある全部位」を列挙
最初に部位リストを作るときは UI 都合で減らさず、臨床的に意味のある単位で全部書く。後から追加するのは大変。

### #42 — CSS の `display: flex` は HTML `hidden` 属性に勝つ
モーダルに `display: flex; ` を直接付けると `hidden` 属性が無視される。`:not([hidden])` で防ぐか、`display: none !important` を `[hidden]` に付ける。

### #43 — iPhone モーダルは下端タブで隠れる
画面下端のタブナビゲーション + Safari ホームバーで、モーダルのアクションボタンが隠れる。対策:
- モーダル overlay: `align-items: flex-start`(上寄せ)
- カード: `margin-bottom: 80px`
- アクション: `position: sticky; bottom: 0`
- ボタン: `min-height: 44px`(iOS HIG)

### #44 — 手動構築 FormData に新フィールド追加忘れ注意
`saveRecord()` のように `new FormData()` で空オブジェクトを作って手動 `append()` する関数では、フォームに新フィールドを追加したら**JS 側でも `formData.append` を追加する必要**がある。`<form>` 要素を `new FormData(form)` で渡す方式なら自動で含まれるが、手動構築方式だと漏れに注意。新フィールド追加時は **`grep "formData.append" templates/input.html`** で append 一覧を確認するクセを。

### #45 — Session ハンドオフ書の「適用済み」記述を盲信しない
Session 35 ハンドオフ書には「dev に `patient_evaluations` 適用済み」と書かれていたが、Session 36 で `information_schema` で確認したら**未作成**だった。ハンドオフ書の事実主張は必ず**実 DB クエリで再確認**してから次に進む(教訓 #38 の拡張)。

---

## 🚀 Session 37 でやること

### 最優先

1. **README.md 更新**: Session 36 Phase 2.A 完了反映、教訓 #39〜#45 追加(過去 README には #29〜#38 がある)
2. **`docs/SESSION37_HANDOFF.md`** の確定版を git commit & push
3. **作業ファイル削除**: ルートに残っている `vas_coordinates_editor.html`、`vas_polygon_editor_v2.html`(Untracked、座標調整用の使い捨てツール)
4. これら全部を **tasukaru-dev** に commit & push(本番マージは不要、コードは既に本番済み)

### その後の選択肢(ZIMAX と相談)

| 候補 | 内容 | 規模 |
|---|---|---|
| Phase 2.B | 月次評価 22 項目の入力 UI と DB 構築 | 大(数セッション) |
| Phase 2.C | ケアマネ書類 PDF 出力 | 大 |
| 細かな改善 | iOS スワイプジェスチャ、印刷スタイル、月間 VAS グラフ | 中 |
| AI 統合 | 既存の AI 統合記録に VAS データを含める | 中 |

設計の詳細は `docs/CARE_MANAGER_REPORT_DESIGN.md` 参照。

---

## 🔧 環境メモ

| 環境 | Supabase プロジェクト | Cloud Run | URL |
|---|---|---|---|
| **本番** | `abvglnkwtdeoaazyqwyd` | `tasukaru` | https://tasukaru-191764727533.asia-northeast1.run.app |
| **dev** | `otjevnmoycnvaxeltrtj` | `tasukaru-dev` | https://tasukaru-dev-191764727533.asia-northeast1.run.app |

### Git ブランチ運用(教訓 #29 厳守)

- ローカル作業: **常に `tasukaru-dev`** で commit
- 本番リリース: `tasukaru` に切り替え → `git merge tasukaru-dev` → `git push origin tasukaru` → **即座に `git checkout tasukaru-dev`** で戻る
- VSCode 左下のブランチ表示を毎回確認

### 本番リリース順序(教訓 #30 厳守)

1. 本番 Supabase に DDL 適用(マイグレーション)
2. 本番ブランチへコードマージ・push
3. Cloud Build 完了確認
4. iPhone で実機動作確認
5. `tasukaru-dev` に戻る

---

## 🧠 重要な教訓の再確認

| 番号 | 内容 |
|---|---|
| **#27** | Supabase SQL Editor の autocomplete は時々暴走。コード貼り直しで対処 |
| **#28** | `CREATE TABLE` 時は `IF NOT EXISTS` を付ける |
| **#29** | 作業中は常に `tasukaru-dev`、本番マージ後すぐ戻る |
| **#30** | 本番リリースは DB → コード順厳守 |
| **#32** | ファイル受領時は必ずハッシュ照合 |
| **#34** | iPhone 実機で必ず最終確認(デスクトップで OK でも実機で破綻するパターンあり)|
| **#38** | ハンドオフ書を盲信せず、実コード・実 DB で確認 |
| **#42** | `display: flex` は `hidden` 属性に勝つ |
| **#43** | iPhone モーダルは下端タブで隠れる |
| **#44** | 手動 FormData の append 漏れに注意 |
| **#45** | ハンドオフ書の「適用済み」記述は実 DB で再確認 |

---

**Session 36 完了 / Phase 2.A 本番リリース達成 🎉**
**次のセッションへ — ハッピーな引き継ぎを!**
