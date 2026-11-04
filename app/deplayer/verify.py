# -*- coding: utf-8 -*-
"""Перевірка готового файла без плати й без симулятора.

Що перевіряється:
  1. ELF: формат ARM, точка входу, сегменти програми й треку не перекриваються.
  2. Заголовок треку: ті самі вимоги, що й у програвачі, плюс межі сегмента.
  3. Контрольна сума — та сама, яку рахує програвач перед стартом.
  4. Незалежне розпакування всіх блоків і порівняння з підготовленими
     відліками, тобто вже після зміни частоти й вирівнювання гучності (SNR).
  5. Чи вміститься файл у звичайний CPUlator.
"""
import numpy as np

from . import blob as blobmod
from . import elf
from .targets import CPULATOR_PLAIN_LIMIT


def snr_db(ref, got):
    ref = ref.astype(np.float64)
    err = ref - got.astype(np.float64)
    pe = float(np.mean(err ** 2))
    ps = float(np.mean(ref ** 2))
    if pe == 0:
        return float('inf')
    return 10 * np.log10(ps / pe) if ps > 0 else 0.0


def check(elf_raw, reference=None):
    """Повертає (успіх, список рядків звіту, словник чисел)."""
    lines, nums, ok = [], {}, True

    def bad(msg):
        nonlocal ok
        ok = False
        lines.append('ПОМИЛКА: ' + msg)

    try:
        t = elf.read(elf_raw)
    except elf.ElfError as e:
        return False, ['ПОМИЛКА: ' + str(e)], nums
    base = t['symbols'].get('__blob_base')
    if base is None:
        return False, ['ПОМИЛКА: немає символу __blob_base'], nums
    seg = [s for s in t['segments'] if s['vaddr'] == base]
    if not seg:
        return False, ['ПОМИЛКА: у файлі немає сегмента треку'], nums
    code = [s for s in t['segments'] if s['vaddr'] != base]
    lines.append('ELF: ARM, точка входу 0x%08X, програма %d байтів, трек за адресою 0x%08X'
                 % (t['entry'], sum(s['filesz'] for s in code), base))
    raw = seg[0]['data']

    h = blobmod.parse(raw)
    problems = blobmod.header_errors(h)
    if h['data_off'] + h['data_size'] > len(raw):
        problems.append('дані треку виходять за межі сегмента')
    for p in problems:
        bad(p)
    if problems:
        return ok, lines, nums
    nb, bs = h['blocks'], h['block_samples']
    dur = h['total_samples'] / h['rate']
    lines.append('Трек: %s, %d Гц, %s, %d блоків по %d відліків, %d:%02d'
                 % (h['codec_name'].upper(), h['rate'], 'стерео' if h['channels'] == 2 else 'моно',
                    nb, bs, int(dur) // 60, int(dur) % 60))
    nums.update(rate=h['rate'], channels=h['channels'], seconds=dur, codec=h['codec_name'],
                blob_bytes=len(raw), elf_bytes=len(elf_raw))

    cs = blobmod.checksum(raw[h['data_off']:h['data_off'] + h['data_size']])
    if cs != h['checksum']:
        bad('контрольна сума не збігається (0x%08X проти 0x%08X)' % (cs, h['checksum']))
    else:
        lines.append('Контрольна сума 0x%08X збігається, заголовок узгоджений — те саме перевіряє програвач' % cs)

    pcm = blobmod.decode(raw)
    nums['peak_dbfs'] = 20 * np.log10(max(1, int(np.max(np.abs(pcm.astype(np.int32))))) / 32768)
    if reference is not None:
        ref = reference[:, :pcm.shape[1]]
        s = snr_db(ref, pcm[:, :ref.shape[1]])
        nums['snr_db'] = s
        if h['codec_name'] == 'pcm16':
            if s != float('inf'):
                bad('PCM16 не збігається з підготовленими відліками')
            else:
                lines.append('Розпакування збігається з підготовленими відліками біт у біт')
        else:
            lines.append('Розпакування всіх %d блоків: SNR %.1f дБ відносно підготовлених відліків' % (nb, s))
            if s < 15:
                bad('надто низьке відношення сигнал/шум')
    else:
        lines.append('Розпаковано всі %d блоків без помилок' % nb)

    if len(elf_raw) > CPULATOR_PLAIN_LIMIT:
        lines.append('Розмір %.2f МБ: для CPUlator потрібен режим із наперед виділеною пам\'яттю'
                     % (len(elf_raw) / 1e6))
        nums['needs_bigmem'] = True
    else:
        lines.append('Розмір %.2f МБ: вміщується у звичайний CPUlator' % (len(elf_raw) / 1e6))
        nums['needs_bigmem'] = False
    return ok, lines, nums
