# -*- coding: utf-8 -*-
"""Один крок: трек -> файл для плати або CPUlator -> перевірка."""
import os
import re
import time

from . import audio, blob, elf, verify
from .targets import TARGETS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE = os.path.join(ROOT, 'firmware', 'build', 'player.elf')


def safe_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r'[^A-Za-z0-9_-]+', '_', base).strip('_') or 'track'
    return base[:40]


def make(track, target_key, codec='adpcm', channels=2, start=0.0, length=None,
         normalize=True, out_dir=None, log=print):
    """Повертає словник: шляхи файлів, результат перевірки, числа."""
    target = TARGETS[target_key]
    t0 = time.time()
    log('Читаю трек і перераховую на %d Гц...' % target.rate)
    pcm, note = audio.prepare(track, target.rate, channels, start, length, normalize)
    log('  джерело: %d Гц, %d кан., %.1f с, підсилення %+.1f дБ'
        % (note['source_rate'], note['source_channels'], note['seconds'], note['gain_db']))

    log('Кодую %s блоками...' % codec.upper())
    raw, info = blob.build(pcm, codec, target)
    log('  %d блоків по %d байтів, трек %.2f МБ' % (info['blocks'], info['block_bytes'], info['bytes'] / 1e6))

    with open(TEMPLATE, 'rb') as f:
        template = f.read()
    elf_raw = elf.build(template, raw)

    out_dir = out_dir or os.path.join(ROOT, 'output')
    os.makedirs(out_dir, exist_ok=True)
    stem = '%s_%s_%s' % (safe_name(track), target.key, codec)
    elf_path = os.path.join(out_dir, stem + '.elf')
    with open(elf_path, 'wb') as f:
        f.write(elf_raw)
    files = [elf_path]
    if target.board:
        srec_path = os.path.join(out_dir, stem + '.srec')
        with open(srec_path, 'wb') as f:
            f.write(elf.to_srec(elf_raw))
        files.append(srec_path)
    log('Записано: %s (%.2f МБ)' % (os.path.basename(elf_path), len(elf_raw) / 1e6))

    log('Перевіряю файл...')
    ok, lines, nums = verify.check(elf_raw, pcm)
    for ln in lines:
        log('  ' + ln)
    log('Готово за %.1f с — %s' % (time.time() - t0, 'перевірку пройдено' if ok else 'Є ПОМИЛКИ'))
    return {'ok': ok, 'files': files, 'elf': elf_path, 'nums': nums, 'lines': lines,
            'target': target, 'pcm': pcm}
