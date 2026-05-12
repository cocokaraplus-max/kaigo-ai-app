# Session 35 引き継ぎ(Session 34 → 35)

> Session 34 完了時点(2026-05-12)。
> Session 34 は dev に push 済み、本番リリース未実施で終了。

---

## 🔴 最優先タスク: Session 34 の本番リリース

### 内容
Session 34 で完了した2つの改修を本番に反映する。**コードのみの変更で DB 変更は一切なし**。

#### A) `templates/board.html`(掲示板コメントドロワー改修)
- iOS キーボード追従(`visualViewport` トラッカー)
- シート 60vh 制限 + `dvh` 対応
- 全周フローティング(カード型)、画面角丸との干渉解消
- 空状態のリッチ表示

#### B) `templates/daily_view.html`(スピードダイヤル肉球配置)
- 右下ピンクのメインボタンを中心に、検索 / 全て開く / TOPへ の3つを放射状配置
- 各ラベルが各ボタンと×を結ぶ放射線の延長線上に配置(縦書き/45°回転縦書き/横書き)
- IntersectionObserver による画面表示ベースの既読化
- TOPへスクロール強化(4段階フォールバック)

### 手順(教訓 #30 の DB→コード順は今回該当なし、コードのみ)

```bash
# 1. 現在のブランチ確認
cd /Users/ZIMAX/.../kaigo-ai-app
git status                          # On branch tasukaru-dev であること

# 2. 本番ブランチに切り替えてマージ
git checkout tasukaru
git pull origin tasukaru
git merge tasukaru-dev               # コンフリクトなければそのまま
git push origin tasukaru

# 3. Cloud Build 完走待ち(2-5分)
# https://console.cloud.google.com/cloud-build/builds で確認

# 4. 本番 iPhone で動作確認
# https://tasukaru-191764727533.asia-northeast1.run.app
# - 掲示板でコメント追加(全周フローティングしてるか)
# - ケース記録でメインボタンタップ(肉球配置になってるか)
# - TOPへボタンでスクロール最上部に戻るか
# - IntersectionObserver で画面表示時に既読化されるか

# 5. ブランチを戻す(教訓 #29)
git checkout tasukaru-dev
```

### 直近のローカルファイルハッシュ(参考)
- `templates/board.html`: `6d59588d5d4da2935082396d7203392cbf9c7c3ef5e25cc068c515cb702c9f34`
- `templates/daily_view.html`: `7f317c56ab1a221513156a38e7815e4b03b4016a89d7aa3db4364c1cc8e6bf9b`

---

## 🟡 次のタスク: dev `cocokaraplus-5526` にヒヤリハット追加

Session 33 から持ち越し。本番にはヒヤリハット追加済みだが、dev だけ未対応でスキーマ乖離が残っている。

### dev Supabase SQL Editor で実行

```sql
-- 教訓 #27: 1 文ずつ、短い英字主体、Run without RLS は不要(UPDATE/INSERT)

-- step 1: その他を最後に押し下げ
UPDATE record_categories SET sort_order = 9 WHERE facility_code = 'cocokaraplus-5526' AND name = 'その他';

-- step 2: 休み連絡を sort_order=8 に
UPDATE record_categories SET sort_order = 8 WHERE facility_code = 'cocokaraplus-5526' AND name = '休み連絡';

-- step 3: ヒヤリハットを sort_order=7 で追加
INSERT INTO record_categories (facility_code, name, color, sort_order, is_default) VALUES ('cocokaraplus-5526', 'ヒヤリハット', '#EF4444', 7, false);

-- step 4: 確認
SELECT facility_code, name, sort_order FROM record_categories WHERE facility_code = 'cocokaraplus-5526' ORDER BY sort_order;
```

期待される結果:
```
心身状況 (1) → 訓練状況 (2) → コミュニケーション (3) → 食事 (4) → 排泄 (5) → 入浴 (6) → ヒヤリハット (7) → 休み連絡 (8) → その他 (9)
```

---

## 🟢 余裕があれば

- 旧 README(累積版、4216 行)の取り扱い決定: 完全削除 or `docs/README_ARCHIVE.md` に保存
- 休み連絡カテゴリの AI 判定精度を実運用で観察
- Session 34 の既読化挙動変更(展開→画面表示ベース)の運用フィードバック確認

---

## Session 34 の学び(次回も同じ失敗をしないため)

### 視覚的なズレを推測で直すループに陥った
- 「もう少し寄せて」「重なっている」というフィードバックに対して、推測で数値を変える試行錯誤を10回近く繰り返した
- **正解は実機の `getBoundingClientRect` を実測すること**
- 画面に直接デバッグオーバーレイを出す方式が iPhone Safari でも有効

### CSS の数学を間違えた
- 同サイズ要素同士の場合、`bottom` 値の差 = 中心間距離(ボタンサイズ補正は不要)
- 「半径75px」を実現したいなら、ボタンの `bottom: メイン + 75` でよい

### `position: fixed` の落とし穴
- 座標未指定だとデフォルト位置(HTML 上の元の位置)に出る
- アニメーション元位置として閉時の `bottom`/`right` を必ず明示する

### コミュニケーション
- 抽象的な「もっと寄せて」「整って」は具体的に確認する
- **手書きスケッチをもらうのが最も確実**(肉球配置のような具体メタファーが出たら即依頼)
