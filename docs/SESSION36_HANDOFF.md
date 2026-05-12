# SESSION 36 ハンドオフ書

> **前 Session: 35 / 作成: 2026-05-12 / 担当: ZIMAX + Claude**
> このハンドオフ書を最初に読んで、現状確認から始めること(教訓 #38)。

---

## 🎯 Session 36 のミッション

**Phase 2.A: VAS 入力機能の実装**

設計は完了している。コード実装フェーズに入る。

設計の詳細は必ず以下を読むこと:
- `docs/CARE_MANAGER_REPORT_DESIGN.md` (23 KB, 493 行)

---

## ⚠️ 最初にやること(教訓 #38)

ハンドオフ書を盲信せず、現実を確認してから着手すること。具体的に:

### 1. dev DB の状態確認

```sql
SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name = 'record_vas' ORDER BY ordinal_position;
```

期待: 8 カラム (id, record_id, facility_code, user_name, part, side, vas_value, created_at)

```sql
SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name = 'patient_evaluations' ORDER BY ordinal_position;
```

期待: 23 カラム

```sql
SELECT indexname FROM pg_indexes WHERE tablename = 'patient_evaluations';
```

期待: 2 件 (patient_evaluations_pkey, uq_patient_eval_user_month)

### 2. ブランチ確認

```bash
cd "/Users/ZIMAX 1/dev/kaigo-ai-app"
git status
git branch --show-current
```

期待: `tasukaru-dev` ブランチで作業(教訓 #29)

### 3. 設計ドキュメント存在確認

```bash
ls -la docs/CARE_MANAGER_REPORT_DESIGN.md
shasum -a 256 docs/CARE_MANAGER_REPORT_DESIGN.md
```

期待ハッシュ: `e578dc81812b59bea99471748b7a2152b9b0ed37bdfb924390a0f77e776135ff`

---

## 📋 Session 35 の成果サマリ

### DB 適用済み(dev のみ、本番は未適用)

1. `record_vas` テーブル (8 カラム) ← VAS データ保存先
2. `patient_evaluations` テーブル (23 カラム + UNIQUE 制約)

### 設計確定済み(docs/CARE_MANAGER_REPORT_DESIGN.md 参照)

- VAS 入力 UI 仕様(31 ポイント、illustAC 人体図)
- VAS 部位の座標一覧(viewBox 250×500)
- 月次評価 22 項目の意味と用途
- ケアマネ書類レイアウト(案 A ベース、連携依頼削除版、A4 縦 1 枚)

### 解決した教訓 #38 案件(参考)

- Session 34 本番リリース: 実は完了済みだった
- dev cocokaraplus-5526 ヒヤリハット: 想定通り未追加 → 追加実施
- record_vas 初回作成スキーマ不一致: 原因不明、SELECT で検出 → DROP & 再作成で解消

---

## 🚀 Phase 2.A: VAS 機能実装の作業リスト

### 順序

```
1. 人体図画像を Flask static に配置
2. _vas_widget.html (部分テンプレート) 作成
3. record_input.html 改修 (心身状況・訓練状況選択時に VAS 表示)
4. app.py 改修 (記録保存 API で record_vas にも INSERT)
5. daily_view.html 改修 (VAS 表示追加)
6. dev で動作確認
7. 本番リリース判断(教訓 #30: 本番 DB 適用 → コード push)
```

### 各ファイルの作業内容

#### 1. 人体図画像配置

```bash
mkdir -p static/img/body
# ZIMAX デスクトップから body_front.png, body_back.png を移動
mv "/Users/ZIMAX 1/Desktop/body_front.png" static/img/body/
mv "/Users/ZIMAX 1/Desktop/body_back.png" static/img/body/
shasum -a 256 static/img/body/*.png
```

期待ハッシュ:
- body_front.png: `43116441872c98b170765e7f3990b8f3b511f65cddd4fd088f590d11b140490d`
- body_back.png: `d12b96d9a0d581d614e4db61d04056263f212305f5738cfce16fa3e83f52cd69`

#### 2. _vas_widget.html 作成

設計書 §1.3 のタップ座標 + JS を組み込んだ Jinja2 部分テンプレート。
Session 35 で作った HTML モック (`/home/claude/vas_widget.html`、約 96KB) があるが、画像 base64 が埋め込まれていて巨大。本番では画像参照型に書き直す:

```html
<img src="{{ url_for('static', filename='img/body/body_front.png') }}">
```

SVG とタップ JS は流用可能。

#### 3. record_input.html 改修

- カテゴリ選択時に JS でカテゴリを検知
- `心身状況` `訓練状況` の時だけ VAS ウィジェットを表示
- フォーム送信時に VAS データ配列を hidden field に JSON 化して同梱

#### 4. app.py 改修(保存 API)

擬似コード:
```python
@app.route('/api/records', methods=['POST'])
def save_record():
    # 既存処理: records に INSERT
    record_id = insert_record(...)
    
    # 新規処理: VAS データがあれば record_vas に一括 INSERT
    vas_records = request.json.get('vas_records', [])
    if vas_records:
        for v in vas_records:
            supabase.table('record_vas').insert({
                'record_id': record_id,
                'facility_code': facility_code,
                'user_name': user_name,
                'part': v['part'],
                'side': v['side'],
                'vas_value': v['value']
            }).execute()
    
    return jsonify(ok=True)
```

#### 5. daily_view.html 改修

該当記録に VAS データがあれば、本文の下に簡易表示:
```
左大腿部 VAS 5、下背部(腰部) VAS 3
```

### リスク・地雷

- **タップ座標のズレ**(教訓 #34): ブラウザで実機表示しながら getBoundingClientRect で実測すること。デバッグオーバーレイ有効化推奨
- **VAS データの保存タイミング**: records 作成後に record_vas を INSERT する順序を守る(record_id 必須)
- **iOS Safari でのタップ判定**: SVG circle の hover/click が iOS で渋いことがある。touchstart の併用検討
- **記録編集時の VAS 上書き**: 既存記録を編集する際、既存 record_vas を DELETE してから再 INSERT が安全(UPSERT は record_id+part+side の組合せでないと難しい)

### 期間目安

4-6 時間(Session 36 単独で完結可能)

---

## 📝 Session 36 後半 or Session 37 以降の作業

### Phase 2.A 完了後

1. **本番 Supabase に record_vas 適用**(教訓 #30: DB → コード順)
2. **コードを tasukaru ブランチにマージ → push → Cloud Build → 本番デプロイ**
3. **tasukaru-dev に戻す**(教訓 #29)

### Phase 2.B: 月次評価機能(Session 37 推奨)

- evaluation_input.html 作成
- 新 route `/evaluations` 追加
- evaluation_helper.py 作成(UPSERT ロジック)
- base.html ナビゲーション追加
- monitoring_integration.py 改修(評価データの統合)

### Phase 2.C: ケアマネ書類生成(Session 38-39 推奨)

- care_manager_report.html 作成
- care_manager_report_gen.py 作成
- mappings/<facility>/care_manager_standard.json 作成
- 新 route 3 つ追加
- WeasyPrint 導入(requirements.txt + Dockerfile 更新)
- ナビゲーション追加

---

## 🧠 適用すべき教訓(全 38)

### Session 36 で特に意識すべき

| # | 内容 |
|---|---|
| #29 | 常に tasukaru-dev ブランチ、本番作業時のみ tasukaru、終わり次第戻す |
| #30 | 本番リリースは DB → コード順厳守 |
| #32 | ファイル受領時は SHA-256 で照合 |
| #33 | カテゴリ追加は最低 4-5 箇所同時更新 |
| #34 | 視覚的ズレは推測でなく getBoundingClientRect で実測 |
| #37 | UI 配置は手書きスケッチで確認 |
| **#38** | **ハンドオフ書を盲信せず、現状確認 SELECT/git log/ハッシュ照合を最初に** |

### Session 35 で新規認定された教訓 #38

ハンドオフ書の記述と実態がズレることはよくある。最初に SELECT/git log/ハッシュ照合で現状を確認してから着手する。Session 35 で 3 件発動した。

---

## 📂 関連ファイル一覧

### 設計

- `docs/CARE_MANAGER_REPORT_DESIGN.md` ← **必読**

### 既存(参考読み込み済み、Session 36 で最新版を再確認)

- `monitoring_integration.py`
- `monitoring_gen.py`
- `templates/monitoring.html`
- `template_filler.py`
- `excel_importer.py`

### Session 36 で新規作成

- `static/img/body/body_front.png`
- `static/img/body/body_back.png`
- `templates/_vas_widget.html`

### Session 36 で改修

- `templates/record_input.html`
- `app.py`(記録保存 API 部分)
- `templates/daily_view.html`

---

## 🎬 Session 36 開始時の理想フロー

```
1. このハンドオフ書を読む (5 分)
2. docs/CARE_MANAGER_REPORT_DESIGN.md §1 (VAS の章) を読む (10 分)
3. 「最初にやること」(教訓 #38) を実行 → 現状確認 (5 分)
4. ZIMAX さんに「今日の優先順位は?」を確認 (Phase 2.A で良いか)
5. Phase 2.A に着手
```

---

以上。健闘を祈る!
