@echo off
rem DE1-SoC Audio Player: перший запуск сам створює середовище й ставить бібліотеки.
chcp 65001 >nul
cd /d "%~dp0"

rem Середовище лежить поза текою проєкту (щоб OneDrive/Git не тягали тисячі файлів)
rem і не в AppData (Python із Microsoft Store перенаправляє туди записи в інше місце).
set VENV=%USERPROFILE%\.de1soc-audio-player\venv
set PY=%VENV%\Scripts\python.exe

if exist "%PY%" (
    fc /b requirements.txt "%VENV%\requirements.txt" >nul 2>&1 && (
        "%PY%" -c "import miniaudio, numpy, websocket, tkinter" >nul 2>&1 && goto run
    )
)

echo Перший запуск: готую середовище Python і ставлю бібліотеки (один раз, ~1 хв)...

rem Шукаємо звичайний Python 3.10+ (варіант без GIL "3.13t" не підходить: під нього
rem немає готових бібліотек).
set BASEPY=
for %%V in (3.12 3.13 3.11 3.10 3.14) do (
    if not defined BASEPY (
        py -%%V -c "import sys; sys.exit(0 if getattr(sys, '_is_gil_enabled', lambda: True)() else 1)" >nul 2>&1 && set "BASEPY=py -%%V"
    )
)
if not defined BASEPY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) and getattr(sys, '_is_gil_enabled', lambda: True)() else 1)" >nul 2>&1 && set "BASEPY=python"
)
if not defined BASEPY (
    echo.
    echo Не знайдено Python 3.10 або новіший. Встановіть його з https://www.python.org/downloads/
    echo ^(під час встановлення позначте "Add python.exe to PATH"^) і запустіть run.bat ще раз.
    pause
    exit /b 1
)
echo Python: %BASEPY%

if exist "%VENV%" rmdir /s /q "%VENV%"
%BASEPY% -m venv "%VENV%" || goto fail
"%PY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt || goto fail
copy /y requirements.txt "%VENV%\requirements.txt" >nul
echo Готово.

:run
start "" "%VENV%\Scripts\pythonw.exe" app\main.py
exit /b 0

:fail
echo.
echo Не вдалося встановити бібліотеки. Перевірте інтернет і запустіть run.bat ще раз.
pause
exit /b 1
