@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  set /p KW=输入歌名：
) else (
  set KW=%~1
)
python -m ncm_radar "%KW%" --count 1500
echo.
pause
