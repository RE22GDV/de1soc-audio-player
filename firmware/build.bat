@echo off
rem Перезбирання шаблону програвача build\player.elf.
rem Потрібен набір інструментів arm-altera-eabi з Intel FPGA Monitor Program 18.1.
rem Для звичайної роботи застосунку перезбирати не треба: player.elf уже в репозиторії.
chcp 65001 >nul
cd /d "%~dp0"
set TOOLS=C:\intelFPGA_lite\18.1\University_Program\Monitor_Program\arm_tools\baremetal\bin
if not exist "%TOOLS%\arm-altera-eabi-gcc.exe" (
    echo Не знайдено %TOOLS%\arm-altera-eabi-gcc.exe
    echo Встановіть Intel FPGA Monitor Program 18.1 або вкажіть шлях у змінній TOOLS.
    pause
    exit /b 1
)
set PATH=%TOOLS%;%PATH%
if not exist build mkdir build
set CFLAGS=-O2 -Wall -Wextra -marm -mcpu=cortex-a9 -mfloat-abi=soft -ffreestanding -fno-builtin
arm-altera-eabi-gcc %CFLAGS% -c crt0.s -o build\crt0.o || goto fail
arm-altera-eabi-gcc %CFLAGS% -c player.c -o build\player.o || goto fail
arm-altera-eabi-gcc %CFLAGS% -nostdlib -nostartfiles -T player.ld build\crt0.o build\player.o -lgcc -o build\player.elf || goto fail
arm-altera-eabi-size build\player.elf
echo Готово: build\player.elf
exit /b 0
:fail
echo Помилка збирання
exit /b 1
