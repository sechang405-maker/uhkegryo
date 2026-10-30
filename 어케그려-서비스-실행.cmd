@echo off
chcp 65001 >nul
title 어케그려 서비스 실행
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\portfolio-host-online.ps1"
if errorlevel 1 (
  echo.
  echo 실행에 실패했습니다. 이 창의 오류와 .local-run\portfolio-host 로그를 확인하세요.
  pause
  exit /b 1
)
echo.
echo 어케그려 공개 서비스가 준비되었습니다.
echo https://uhkegryo-xi.vercel.app
pause

