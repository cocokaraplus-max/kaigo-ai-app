# 段階2-c アップデート: フォールバック＆利用曜日

## 🎯 追加・改良した機能

### ① フォールバック機能
最新月のモニタリングシートで空欄の項目があっても、過去月のシートから自動で値を探して補完します。

### ② 利用曜日の抽出
ケース記録シートの `B51` から「火・午前」などの利用曜日を抽出します。

### ③ 画面でのフォールバック可視化
各項目に3つのステータスバッジを表示:
- 🟢 取得済（最新月から）
- 🟡 過去月から（フォールバック発動）
- 🔴 空欄

## 📦 差し替えファイル

| ファイル | 配置先 |
|---|---|
| `excel_importer.py` | `~/Desktop/kaigo-ai-app/` （**上書き**） |
| `patient_info_import.html` | `~/Desktop/kaigo-ai-app/templates/` （**上書き**） |
| `add_usage_weekday.sql` | Supabase SQL Editorで実行（**新規**） |

## 🔧 適用手順

### ステップ1: SQL実行

Supabase Dashboard → SQL Editor → `add_usage_weekday.sql` の中身を貼り付け → Run

これで `patient_care_plans` テーブルに `usage_weekday` カラムが追加されます。

### ステップ2: ファイル差し替え

```bash
cd ~/Desktop/kaigo-ai-app

# バックアップ
cp excel_importer.py excel_importer.py.bak
cp templates/patient_info_import.html templates/patient_info_import.html.bak

# 差し替え
cp ~/Downloads/stage2c/excel_importer.py ./
cp ~/Downloads/stage2c/patient_info_import.html templates/
```

### ステップ3: 再起動

```bash
python3 app.py
```

## 🚀 使い方（変更なし）

ブラウザで `http://localhost:8080/patient-info/import` → ファイルをドラッグ&ドロップ

新機能の動作:
- 解析が終わると、**「過去月から」** バッジが付く項目があれば警告ボックスが表示される
- 利用曜日の欄が新しく追加されている
- 内容を確認して「この内容で登録」

## 📊 実際のテスト結果

添付していただいたExcelファイル（34シート）で検証:
- ✅ 最新月（R8.4）から最大限取得
- ✅ 担当者欄がR8.4で空だったため、R8.3から自動補完 ⤴
- ✅ 利用曜日「火・午前」をケース記録R8.4から取得
- ✅ **全23項目埋まった**（23/23）

## 💡 こんな時に役立ちます

### ケース1: 最新月のモニタリングをまだ書いていない
→ 過去月から自動で拾ってくるので、抜け漏れが発生しない

### ケース2: 様式が新しくなって項目が追加された
→ 古い月には無い項目だけ、新しい月から拾える

### ケース3: 入力者によって空欄が発生している
→ 他の月で入っていれば自動補完
