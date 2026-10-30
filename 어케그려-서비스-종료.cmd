@echo off
chcp 65001 >nul
title 어케그려 서비스 종료
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\portfolio-host-stop.ps1"
if errorlevel 1 (
  echo.
  echo 종료에 실패했습니다. 이 창의 오류와 .local-run\portfolio-host 로그를 확인하세요.
  pause
  exit /b 1
)
echo.
echo 어케그려 로컬 서비스와 터널을 종료했습니다. 저장 데이터와 일일 사용량은 보존됩니다.
pause

