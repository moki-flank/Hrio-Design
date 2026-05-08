@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [Hrio Design] 初始化 Git 仓库...
git init
if errorlevel 1 goto :err

git branch -M main

git remote remove origin >nul 2>nul
git remote add origin git@github.com:moki-flank/Hrio-Design.git

echo [Hrio Design] 添加文件...
git add -A

echo [Hrio Design] 提交 release v8.1.0...
git commit -m "release Hrio Design v8.1.0" || echo [Hrio Design] 没有新的改动可提交，继续推送...

echo [Hrio Design] 推送到 GitHub main...
git push -u origin main
if errorlevel 1 goto :err

echo.
echo [Hrio Design] 完成。GitHub Actions 会自动发布到 Comfy Registry。
pause
exit /b 0

:err
echo.
echo [Hrio Design] 执行失败，请确认：
echo 1. 已安装 Git
echo 2. SSH Key 已加入 GitHub
echo 3. 仓库地址 git@github.com:moki-flank/Hrio-Design.git 可访问
echo 4. GitHub Secrets 已添加 REGISTRY_ACCESS_TOKEN
pause
exit /b 1
