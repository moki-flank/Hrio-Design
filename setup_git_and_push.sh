#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "[Hrio Design] 初始化 Git 仓库..."
git init
git branch -M main

git remote remove origin >/dev/null 2>&1 || true
git remote add origin git@github.com:moki-flank/Hrio-Design.git

echo "[Hrio Design] 添加文件..."
git add -A

echo "[Hrio Design] 提交 release v8.1.0..."
git commit -m "release Hrio Design v8.1.0" || echo "[Hrio Design] 没有新的改动可提交，继续推送..."

echo "[Hrio Design] 推送到 GitHub main..."
git push -u origin main

echo "[Hrio Design] 完成。GitHub Actions 会自动发布到 Comfy Registry。"
