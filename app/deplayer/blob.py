# -*- coding: utf-8 -*-
"""Формат треку "DE1A": 64 байти заголовка + блоки однакового розміру."""
import struct

import numpy as np

from . import codec
from .targets import BLOCK, METER_HZ

MAGIC = b'DE1A'
VERSION = 1
HEADER = struct.Struct('<4sHHIHHIIIIIIIIII8s')     # 64 байти
CODECS = {'pcm16': 0, 'adpcm': 1}
FLAG_HEX = 0x1
RATES = (8000, 48000)
MAX_BLOCK = 2048
MAX_QUEUE = 65536
BLOB_BASE = 0x00200000
DDR_END = 0x40000000
assert HEADER.size == 64


def checksum(data):
    """Сума 32-розрядних слів (дані доповнено нулями до кратного 4)."""
    pad = (-len(data)) % 4
    w = np.frombuffer(data + b'\0' * pad, dtype='<u4')
    return int(w.sum(dtype=np.uint64) & 0xFFFFFFFF)


def build(pcm, codec_name, target):
    """pcm: int16 [канали, відліки]. Повертає (bytes треку, опис)."""
    ch, n = pcm.shape
    nb = (n + BLOCK - 1) // BLOCK
    padded = np.zeros((ch, nb * BLOCK), dtype=np.int16)
    padded[:, :n] = pcm
    data, block_bytes = codec.encode_blocks(padded, codec_name, BLOCK)
    data += b'\0' * ((-len(data)) % 4)
    hdr = HEADER.pack(MAGIC, VERSION, CODECS[codec_name], target.rate, ch, BLOCK,
                      nb, block_bytes, n, HEADER.size, len(data), checksum(data),
                      FLAG_HEX if target.hex else 0, target.latency,
                      target.rate // METER_HZ, target.max_lag, b'\0' * 8)
    info = {'blocks': nb, 'block_bytes': block_bytes, 'samples': n,
            'bytes': HEADER.size + len(data)}
    return hdr + data, info


def parse(blob):
    """Розбирає заголовок. Повертає словник полів (без перевірок)."""
    f = HEADER.unpack_from(blob, 0)
    keys = ('magic', 'version', 'codec', 'rate', 'channels', 'block_samples', 'blocks',
            'block_bytes', 'total_samples', 'data_off', 'data_size', 'checksum', 'flags',
            'latency', 'meter_win', 'max_lag', 'reserved')
    h = dict(zip(keys, f))
    h['codec_name'] = {v: k for k, v in CODECS.items()}.get(h['codec'], '?')
    return h


def header_errors(h):
    """Ті самі вимоги до заголовка, що й у header_ok() програвача (firmware/player.c).
    Повертає список зауважень, порожній — усе узгоджено."""
    if h['magic'] != MAGIC or h['version'] != VERSION:
        return ['невідома сигнатура або версія треку']
    if h['codec'] not in CODECS.values():
        return ['невідомий кодек %d' % h['codec']]
    err = []
    if h['rate'] not in RATES:
        err.append('непідтримувана частота %d Гц' % h['rate'])
    ch, bs, nb = h['channels'], h['block_samples'], h['blocks']
    if ch not in (1, 2):
        err.append('непідтримувана кількість каналів %d' % ch)
    if not 0 < bs <= MAX_BLOCK:
        return err + ['блок на %d відліків (допустимо 1…%d)' % (bs, MAX_BLOCK)]
    if h['codec_name'] == 'adpcm':
        if bs & 1:
            err.append('для ADPCM потрібна парна кількість відліків у блоці')
        expect = ch * (4 + bs // 2)
    else:
        expect = ch * bs * 2
    if h['block_bytes'] != expect:
        err.append('розмір блоку %d замість %d' % (h['block_bytes'], expect))
    if nb == 0:
        err.append('у треку немає блоків')
    if not nb * bs - bs < h['total_samples'] <= nb * bs or h['total_samples'] == 0:
        err.append('%d відліків не відповідають %d блокам' % (h['total_samples'], nb))
    if h['data_off'] != HEADER.size:
        err.append('зміщення даних %d замість %d' % (h['data_off'], HEADER.size))
    if h['data_size'] != (nb * h['block_bytes'] + 3) & ~3:
        err.append('розмір даних %d не відповідає блокам' % h['data_size'])
    if BLOB_BASE + h['data_off'] + h['data_size'] > DDR_END:
        err.append('дані виходять за межі пам\'яті DDR3')
    if h['meter_win'] != h['rate'] // METER_HZ:
        err.append('вікно шкали %d відліків замість %d' % (h['meter_win'], h['rate'] // METER_HZ))
    if h['latency'] > MAX_QUEUE or h['max_lag'] > MAX_QUEUE:
        err.append('завелика затримка черги')
    if h['flags'] & ~FLAG_HEX:
        err.append('невідомі прапорці 0x%X' % h['flags'])
    return err


def decode(blob):
    """Незалежне розпакування треку. Повертає int16 [канали, відліки]."""
    h = parse(blob)
    raw = blob[h['data_off']:h['data_off'] + h['data_size']]
    pcm = codec.decode_blocks(raw, h['codec_name'], h['channels'], h['block_samples'], h['blocks'])
    return pcm[:, :h['total_samples']]
