#!/bin/bash
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='*.pyc' --exclude='.DS_Store' "/Users/ZIMAX 1/Desktop/kaigo-ai-app/" "/Volumes/HIRO'sUSB/TASUKARU_backup_$(date +%Y%m%d_%H%M)/"
echo "✅ バックアップ完了"
