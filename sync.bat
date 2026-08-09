@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Quantiva Git 同步助手
echo ============================================
git status --short
echo.
set /p MSG="提交说明: "
if "%MSG%"=="" set MSG=update
git add -A
git commit -m "%MSG%"
if errorlevel 1 goto :fail
echo.
echo 推送中（网络不稳会自动重试）...
set OK=0
for /L %%i in (1,1,8) do (
  git push origin main >nul 2>&1
  if not errorlevel 1 ( set OK=1 & goto :pushed )
  echo   第 %%i 次失败，5 秒后重试...
  timeout /t 5 /nobreak >nul
)
:pushed
if "%OK%"=="1" (
  echo.
  echo [OK] 已推送到 GitHub
) else (
  echo [FAIL] 推送失败，请检查网络后重新运行本脚本
)
echo.
set /p TAG="是否发布新版本？输入版本号（如 v1.5.0）后回车，直接回车跳过: "
if not "%TAG%"=="" (
  git tag %TAG%
  git push origin %TAG%
  echo [OK] 已触发 GitHub Release 自动发布
)
goto :end
:fail
echo [FAIL] 提交失败（可能没有改动）
:end
pause
