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


def decode(blob):
    """Незалежне розпакування треку. Повертає int16 [канали, відліки]."""
    h = parse(blob)
    raw = blob[h['data_off']:h['data_off'] + h['data_size']]
    pcm = codec.decode_blocks(raw, h['codec_name'], h['channels'], h['block_samples'], h['blocks'])
    return pcm[:, :h['total_samples']]
