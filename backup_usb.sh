#!/bin/bash
# ============================================
# TASUKARU USBバックアップスクリプト
# 使い方: ./backup_usb.sh
# ============================================

# スクリプト自身の場所（kaigo-ai-appフォルダ）を基準にする
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
FOLDER_NAME="$(basename "$SCRIPT_DIR")"
BACKUP_NAME="TASUKARU_backup_$(date '+%Y%m%d_%H%M%S')"

# ===== USBを自動検出 =====
USB_PATH="/Volumes/HIRO'sUSB"

if [ ! -d "$USB_PATH" ]; then
    echo "「HIRO'sUSB」が見つかりません。接続中のUSBを探しています..."
    FOUND=$(ls /Volumes/ | grep -v "Macintosh HD" | grep -v "^$" | head -1)
    if [ -z "$FOUND" ]; then
        echo "❌ USBメモリが見つかりません"
        echo "USBが刺さっているか確認してください"
        exit 1
    fi
    USB_PATH="/Volumes/$FOUND"
    echo "✅ USBを検出しました: $USB_PATH"
fi

# ===== バックアップフォルダ作成 =====
BACKUP_DIR="$USB_PATH/TASUKARU_backups"
mkdir -p "$BACKUP_DIR"

echo "🦝 TASUKARUバックアップ開始..."
echo "📁 対象: $PROJECT_DIR"
echo "📁 保存先: $BACKUP_DIR/$BACKUP_NAME.zip"

# ===== zipに圧縮してUSBにコピー =====
cd "$PARENT_DIR"
zip -r "$BACKUP_DIR/$BACKUP_NAME.zip" \
    "$FOLDER_NAME/" \
    --exclude "$FOLDER_NAME/.git/*" \
    --exclude "$FOLDER_NAME/__pycache__/*" \
    --exclude "$FOLDER_NAME/*.pyc" \
    --exclude "$FOLDER_NAME/.DS_Store" \
    --exclude "$FOLDER_NAME/.venv/*" \
    -q

if [ $? -eq 0 ]; then
    SIZE=$(du -sh "$BACKUP_DIR/$BACKUP_NAME.zip" | cut -f1)
    echo "✅ バックアップ完了！（$SIZE）"
    echo "📦 ファイル: $BACKUP_NAME.zip"
    echo "📍 場所: $BACKUP_DIR"
    echo ""
    ls -t "$BACKUP_DIR"/*.zip 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null
    echo "💡 最新10件を保持・古いものは自動削除"
else
    echo "❌ バックアップに失敗しました"
    exit 1
fi