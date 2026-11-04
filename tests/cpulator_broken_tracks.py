# -*- coding: utf-8 -*-
"""Програвач у CPUlator на зіпсованих файлах: python tests/cpulator_broken_tracks.py [назва]

Кожен файл має дати блимання світлодіодів через один, правильний — рух шкали.
Аргумент — частина назви випадку, якщо треба повторити лише його.
Потрібні інтернет і Chrome або Edge.
"""
import os
import struct
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'app'))
from deplayer import blob, cdp, check, elf, helper   # noqa: E402
from deplayer.targets import BLOCK, TARGETS          # noqa: E402

ERROR_PATTERNS = {'1010101010', '0101010101'}
# зміщення полів заголовка (таблиця у README та firmware/player.c)
FIELDS = {'codec': (6, '<H'), 'rate': (8, '<I'), 'channels': (12, '<H'), 'block_samples': (14, '<H'),
          'blocks': (16, '<I'), 'block_bytes': (20, '<I'), 'total_samples': (24, '<I'),
          'data_off': (28, '<I'), 'data_size': (32, '<I'), 'flags': (40, '<I'),
          'latency': (44, '<I'), 'meter_win': (48, '<I')}


def track():
    t = np.arange(8000 * 20) / 8000
    tone = (9000 * np.sin(2 * np.pi * 440 * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 1.7 * t))).astype(np.int16)
    raw, _ = blob.build(np.tile(tone, (2, 1)), 'adpcm', TARGETS['cpulator'])
    return raw


def with_field(raw, name, value):
    off, fmt = FIELDS[name]
    out = bytearray(raw)
    struct.pack_into(fmt, out, off, value)
    return bytes(out)


def cases(raw):
    h = blob.parse(raw)
    yield 'правильний файл', raw, False
    yield 'codec = 7', with_field(raw, 'codec', 7), True
    yield 'rate = 44100', with_field(raw, 'rate', 44100), True
    yield 'channels = 3', with_field(raw, 'channels', 3), True
    yield 'block_samples = 1023', with_field(raw, 'block_samples', 1023), True
    yield 'block_bytes + 2', with_field(raw, 'block_bytes', h['block_bytes'] + 2), True
    yield 'blocks + 1', with_field(raw, 'blocks', h['blocks'] + 1), True
    yield 'total_samples завеликий', with_field(raw, 'total_samples', h['blocks'] * BLOCK + 1), True
    yield 'total_samples замалий', with_field(raw, 'total_samples', 1), True
    yield 'data_off = 128', with_field(raw, 'data_off', 128), True
    yield 'data_size поза DDR3', with_field(raw, 'data_size', 0xFFFFFFF0), True
    yield 'meter_win = 0', with_field(raw, 'meter_win', 0), True
    yield 'latency завелика', with_field(raw, 'latency', 1 << 20), True
    yield 'flags = 0x80', with_field(raw, 'flags', 0x80), True
    damaged = bytearray(raw)
    damaged[len(damaged) // 2] ^= 0x55
    yield 'зіпсований байт даних', bytes(damaged), True


def run_case(path, seconds=3.0):
    """Повертає множину станів світлодіодів за кілька секунд роботи."""
    h = helper.start(os.path.dirname(path), 0)
    b = cdp.Browser(h.url_for(os.path.basename(path)))
    try:
        for attempt in range(2):                     # CPUlator без вікна інколи не стартує з першого разу
            for _ in range(60):
                if 'Total size' in (b.js(check.MSG) or ''):
                    break
                time.sleep(0.5)
            if 'Total size' in (b.js(check.MSG) or ''):
                break
            b.call('Page.reload', ignoreCache=True)
            time.sleep(2)
        if 'Total size' not in (b.js(check.MSG) or ''):
            return {'файл не завантажився'}
        c = b.rect("[...document.querySelectorAll('button')].find(x=>x.textContent.trim().startsWith('Continue'))")
        b.click(c['x'] + c['w'] / 2, c['y'] + c['h'] / 2)
        time.sleep(1.0)
        seen, t0 = set(), time.time()
        while time.time() - t0 < seconds:
            seen.add(b.js(check.LEDS) or '')
            time.sleep(0.05)
        return seen
    finally:
        b.close()
        h.stop()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    with open(os.path.join(ROOT, 'firmware', 'build', 'player.elf'), 'rb') as f:
        template = f.read()
    failed = 0
    only = sys.argv[1] if len(sys.argv) > 1 else ''
    with tempfile.TemporaryDirectory() as tmp:
        for name, blob_raw, must_fail in cases(track()):
            if only not in name:
                continue
            path = os.path.join(tmp, 'case.elf')
            with open(path, 'wb') as f:
                f.write(elf.build(template, blob_raw))
            seen = run_case(path)
            blinks = bool(seen) and seen <= ERROR_PATTERNS
            good = blinks == must_fail
            failed += not good
            print('%-3s %-26s %s' % ('OK' if good else 'НІ', name, sorted(seen)[:4]), flush=True)
    print('не пройшло:', failed)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
