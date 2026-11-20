@echo off
chcp 65001 >nul
cd /d "%~dp0"
:: 外部残留的 MC_APP / MC_LIB 会改变「要写哪个库」，先清掉
set MC_APP=
set MC_LIB=
echo ============================================
echo   mortal-coach · 全量重算所有局的解读与配图
echo   约 16~35 秒/局
echo ============================================
set PY=%~dp0runtime\python\python.exe
if exist "%PY%" goto run
where python >nul 2>nul
if errorlevel 1 goto nopython
set PY=python
goto run
:nopython
echo 找不到 Python：请保留 runtime\python 目录，或把 python.exe 加进 PATH。
pause
exit /b 1
:run
"%PY%" scripts\rebuild_all.py --force %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo 重建没有全部成功：退出码 %RC%，请查看上面列出的局名与牌谱库里的 *.status.json
pause
:: pause 会把 ERRORLEVEL 改成 0，所以必须显式把退出码传回去
exit /b %RC%
