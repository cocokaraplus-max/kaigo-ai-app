#!/bin/bash
# =============================================
# TASUKARU USB自動バックアップスクリプト
# 使い方：USBを挿してターミナルで実行
#   bash ~/tasukaru_backup.sh
# または自動実行（後述）
# =============================================

PROJECT_DIR="$HOME/kaigo-ai-app"
BACKUP_NAME="tasukaru_backup_$(date '+%Y%m%d_%H%M%S')"

# ---- USBドライブを自動検出 ----
USB_PATH=""
for vol in /Volumes/*/; do
    # システムドライブ（Macintosh HD等）を除外
    vol_name=$(basename "$vol")
    if [[ "$vol_name" != "Macintosh HD" && "$vol_name" != "Preboot" && \
          "$vol_name" != "Recovery" && "$vol_name" != "VM" && \
          "$vol_name" != "Data" && -w "$vol" ]]; then
        USB_PATH="$vol"
        break
    fi
done

if [ -z "$USB_PATH" ]; then
    echo "❌ USBドライブが見つかりません。USBを挿してから再実行してください。"
    exit 1
fi

DEST="$USB_PATH/TASUKARU_BACKUP/$BACKUP_NAME"
mkdir -p "$DEST"

echo "💾 バックアップ先：$DEST"
echo "📦 バックアップ開始..."

# ---- プロジェクトファイルをコピー ----
rsync -av --progress \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='node_modules' \
    --exclude='.env' \
    "$PROJECT_DIR/" "$DEST/project/"

# ---- README単体もルートにコピー ----
cp "$PROJECT_DIR/README.md" "$DEST/README.md" 2>/dev/null || true

# ---- バックアップ情報ファイルを作成 ----
cat > "$DEST/BACKUP_INFO.txt" << EOF
TASUKARU バックアップ情報
========================
バックアップ日時：$(date '+%Y年%m月%d日 %H:%M:%S')
バックアップ元：$PROJECT_DIR
バックアップ先：$DEST

含まれるファイル：
- project/ ... プロジェクト全体（.git除く）
- README.md ... 開発記録

バックアップ方法：rsync
EOF

# ---- 古いバックアップを整理（最新10件のみ残す） ----
BACKUP_ROOT="$USB_PATH/TASUKARU_BACKUP"
BACKUP_COUNT=$(ls -d "$BACKUP_ROOT"/tasukaru_backup_* 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt 10 ]; then
    echo "🗑️  古いバックアップを削除（最新10件を残す）..."
    ls -d "$BACKUP_ROOT"/tasukaru_backup_* | sort | head -n $(($BACKUP_COUNT - 10)) | xargs rm -rf
fi

echo ""
echo "✅ バックアップ完了！"
echo "   保存先：$DEST"
echo "   合計バックアップ数：$(ls -d "$BACKUP_ROOT"/tasukaru_backup_* 2>/dev/null | wc -l | tr -d ' ')件"
