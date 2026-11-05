# -*- coding: utf-8 -*-
"""Куди готується файл: частота, затримка черги звуку, наявність HEX.

Ці параметри потрапляють у заголовок треку, тому одна й та сама
програма (firmware/build/player.elf) працює і на платі, і в CPUlator.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    key: str
    title: str
    rate: int
    latency: int        # скільки відліків минає від запису в чергу до звучання
    max_lag: int        # на скільки годинник шкали може відставати, відліків
    hex: bool           # чи показувати час на HEX3..HEX0
    board: bool


TARGETS = {
    # У CPUlator черга звуку тримає 8192 відліки й спорожнюється блоками по 2048,
    # а браузер планує кожен блок близько 0,6 с наперед (виміряно через Web Audio,
    # tests/cpulator_sync.py): разом близько 14000 відліків, тобто 1,75 с.
    'cpulator': Target('cpulator', 'CPUlator (8 кГц)', 8000, 14000, 2048, True, False),
    # На платі черга кодека тримає 128 відліків.
    'board8':   Target('board8', 'Плата, система ЛР5 «мікрофон» (8 кГц)', 8000, 128, 160, False, True),
    'board48':  Target('board48', 'Плата, система ЛР5 «LINE IN» (48 кГц)', 48000, 128, 960, False, True),
}

BLOCK = 1024                     # відліків на канал у блоці (128 мс при 8 кГц)
METER_HZ = 50                    # вікон шкали за секунду (по 20 мс)
CPULATOR_PLAIN_LIMIT = 2_300_000 # більший файл звичайний CPUlator не відтворить
