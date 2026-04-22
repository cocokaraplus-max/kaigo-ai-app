# 段階2: 利用者情報画面 導入手順

## 🎯 今回追加する機能

1. **利用者情報編集画面** (`/patient-info`) - 目標と支援内容を事前登録
2. **Supabase テーブル** (`patient_care_plans`) - ケアプラン情報の保存場所
3. **モニタリング書類生成との連携** - 目標・支援内容を自動転記

## 📦 ファイル一覧

| ファイル | 配置先 | 用途 |
|---|---|---|
| `create_patient_care_plans.sql` | Supabase SQL Editor で実行 | テーブル作成 |
| `patient_info_integration.py` | `~/Desktop/kaigo-ai-app/` | Flaskルート（新規） |
| `patient_info.html` | `~/Desktop/kaigo-ai-app/templates/` | 画面（新規） |
| `monitoring_integration.py` | `~/Desktop/kaigo-ai-app/` | 既存を置換（ケアプラン連携追加） |

## 🔧 導入手順

### ステップ1: Supabaseにテーブルを作る

1. Supabase Dashboard にログイン
2. プロジェクト選択（TASUKARU）
3. 左メニュー「**SQL Editor**」→「**New query**」
4. `create_patient_care_plans.sql` の中身を全部コピペ
5. 右下の「**Run**」ボタンをクリック
6. エラーが出なければOK（`Success. No rows returned` みたいな表示が出る）

### ステップ2: ファイルをTASUKARUに配置

```bash
cd ~/Desktop/kaigo-ai-app

# バックアップ
cp monitoring_integration.py monitoring_integration.py.bak

# 新規ファイルを配置
cp ~/Downloads/stage2/patient_info_integration.py ./
cp ~/Downloads/stage2/patient_info.html templates/
cp ~/Downloads/stage2/monitoring_integration.py ./    # 上書き
```

### ステップ3: app.py に1行追加

`app.py` の末尾、既存の `register_monitoring_routes(app)` の次に、1行追加:

```python
from monitoring_integration import register_monitoring_routes
register_monitoring_routes(app)

# ↓ ここを追加
from patient_info_integration import register_patient_info_routes
register_patient_info_routes(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
```

### ステップ4: 起動

```bash
source .venv/bin/activate
python3 app.py
```

起動ログに以下が両方出ればOK:
```
[monitoring] 書類生成ルートを登録しました (Stage2対応)
[patient_info] 利用者情報ルートを登録しました
```

## 🚀 使い方

### 利用者情報を登録する

1. ブラウザで `http://localhost:8080/patient-info` にアクセス
2. 利用者を選択
3. 長期目標・短期目標・支援内容を入力
4. 「この内容で保存」ボタン

### モニタリング書類を生成する

1. `http://localhost:8080/monitoring` にアクセス
2. 今まで通り利用者・月・様式を選択
3. 「AIで下書きを生成」

すると:
- **登録済みの利用者**: 目標と支援内容がケアプランから自動転記（AIは変化・課題・特記事項などの整文に専念）
- **未登録の利用者**: 今まで通りAIが全部生成

## 📊 挙動の違い

### ケアプラン登録あり
```
長期目標(機能):   「歩行機能を維持する」   ← ケアプランから転記
短期目標(機能):   「下肢筋力を維持する」   ← ケアプランから転記
モニタリング項目①: 「個別機能訓練（週3回）」 ← ケアプランから転記
変化:            「今月は安定して…」     ← AIが記録から整文
特記事項:         「ご家族より…」        ← AIが記録から整文
```

### ケアプラン登録なし（従来通り）
```
長期目標(機能):   AIが記録から推測
モニタリング項目①: AIが記録から推測
変化:            AIが記録から整文
```

## 🎨 ナビゲーションへの追加（任意）

`base.html` のナビゲーションメニューに「利用者情報」リンクを追加すると便利:

```html
<a href="/patient-info" class="{% block nav_patient_info %}{% endblock %}">
    <span class="material-symbols-outlined">person_book</span>
    利用者情報
</a>
```

（追加は任意。URL `/patient-info` に直接アクセスすれば使えます）

## 🐛 トラブル時

### 「利用者情報ルートを登録しました」が出ない
→ `app.py` への追加行を確認。`from patient_info_integration import...` が正しく書かれているか。

### Supabaseエラー
→ `create_patient_care_plans.sql` がちゃんと実行されたか、Supabase Dashboardで `patient_care_plans` テーブルが存在するか確認。

### 保存しても反映されない
→ ブラウザの開発者ツール（F12）のコンソールタブでエラーが出ていないか確認。ネットワークタブで `/api/patient-info/save` のレスポンスを確認。
