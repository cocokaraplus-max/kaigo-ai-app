# 段階2-b: 既存Excel一括インポート機能 導入手順

## 🎯 追加機能

運用中のExcelファイル（ケース記録＋モニタリング）をアップロードするだけで、
利用者の目標・支援内容を `patient_care_plans` テーブルに一括登録できます。

### 特徴
- 最新月のモニタリング報告書シートを**自動判定**（R8.4 など）
- 抽出結果を**プレビュー画面で確認・修正**できる
- 過去月の古い情報は使わない設計
- ドラッグ&ドロップでアップロード可能

## 📦 ファイル一覧

| ファイル | 配置先 | 用途 |
|---|---|---|
| `excel_importer.py` | `~/Desktop/kaigo-ai-app/` | 解析ロジック（新規） |
| `patient_info_import_integration.py` | `~/Desktop/kaigo-ai-app/` | Flaskルート（新規） |
| `patient_info_import.html` | `~/Desktop/kaigo-ai-app/templates/` | 画面（新規） |

## 🔧 導入手順

### 前提: 段階2の利用者情報画面が導入済みであること
段階2のSQL実行、`patient_info_integration.py` の配置が完了している前提です。

### ステップ1: ファイル配置

```bash
cd ~/Desktop/kaigo-ai-app

cp ~/Downloads/stage2b/excel_importer.py ./
cp ~/Downloads/stage2b/patient_info_import_integration.py ./
cp ~/Downloads/stage2b/patient_info_import.html templates/
```

### ステップ2: app.py に1行追加

既存の `register_patient_info_routes(app)` の次に追加:

```python
from patient_info_integration import register_patient_info_routes
register_patient_info_routes(app)

# ↓ ここを追加
from patient_info_import_integration import register_import_routes
register_import_routes(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
```

### ステップ3: 起動

```bash
python3 app.py
```

起動ログに以下が出ればOK:
```
[patient_info_import] Excelインポートルートを登録しました
```

## 🚀 使い方

1. ブラウザで `http://localhost:8080/patient-info/import` にアクセス
2. 既存の運用Excelファイルをドラッグ&ドロップ（または選択）
3. 解析結果を確認
   - 最新月のシート名が表示される（例: "令和8年4月"）
   - 各項目に「取得済」or「空欄」のバッジ
   - 内容を必要に応じて修正
4. 「この内容で登録」

## 💡 対応している様式

現状、ココカラプラスさんの様式を前提に作られています。セル位置:

- フリガナ: D11
- 氏名: D12
- 性別: H12
- 生年月日: I12
- 要介護度種別: O12、数字: Q12
- 短期目標: D15〜D17（機能/活動/参加）、O14〜S14（期間）
- 長期目標: D19〜D21、O18〜S18
- 支援内容①〜④: C32〜C35

他の様式を使っている場合は `excel_importer.py` の `EXTRACTION_MAP` を調整してください。

## 🐛 トラブル時

### 「モニタリング報告書のシートが見つかりません」
シート名に「モニタリング」が含まれていない可能性。実際のシート名を教えてください。

### 「最新月の判定がおかしい」
シート名が「R8.4」のような元号形式でない場合に起こります。現状は:
- 元号表記: `R7.10`, `R8.4` など ✅
- 西暦表記: `2026.04`, `2026-04` など ✅
- それ以外: ❌

## 📝 次のステップ候補

- 複数ファイル一括アップロード対応（現状は1ファイルずつ）
- 取り込んだ月を patient_care_plans に記録（履歴追跡用）
- ケース記録の履歴インポート（現状は対象外）
