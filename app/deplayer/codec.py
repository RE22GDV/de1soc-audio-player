# -*- coding: utf-8 -*-
"""IMA ADPCM і PCM16 блоками — точне дзеркало декодера в firmware/player.c.

Блоки незалежні: на початку кожного лежить стан декодера, тому програвач
може почати з будь-якого блоку (перезапуск, перемотування). Завдяки цьому
кодер обробляє всі блоки одночасно масивами numpy — цикл іде лише по
відліках усередині блоку, а не по всьому треку.
"""
import numpy as np

STEP = np.array([
        7,     8,     9,    10,    11,    12,    13,    14,    16,    17,
       19,    21,    23,    25,    28,    31,    34,    37,    41,    45,
       50,    55,    60,    66,    73,    80,    88,    97,   107,   118,
      130,   143,   157,   173,   190,   209,   230,   253,   279,   307,
      337,   371,   408,   449,   494,   544,   598,   658,   724,   796,
      876,   963,  1060,  1166,  1282,  1411,  1552,  1707,  1878,  2066,
     2272,  2499,  2749,  3024,  3327,  3660,  4026,  4428,  4871,  5358,
     5894,  6484,  7132,  7845,  8630,  9493, 10442, 11487, 12635, 13899,
    15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767], dtype=np.int32)
INDEX = np.array([-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8], dtype=np.int32)
WARMUP = 32        # відліків попереднього блоку, на яких кодер «розганяє» крок


def _encode_step(s, pred, index):
    """Один відлік для всіх блоків разом. Повертає (код, новий pred, новий index)."""
    step = STEP[index]
    diff = s - pred
    code = np.where(diff < 0, 8, 0).astype(np.int32)
    diff = np.abs(diff)
    delta = step >> 3
    m = diff >= step
    code |= m * 4
    diff = diff - step * m
    delta = delta + step * m
    st = step >> 1
    m = diff >= st
    code |= m * 2
    diff = diff - st * m
    delta = delta + st * m
    st = step >> 2
    m = diff >= st
    code |= m * 1
    delta = delta + st * m
    pred = np.clip(np.where(code & 8, pred - delta, pred + delta), -32768, 32767)
    index = np.clip(index + INDEX[code], 0, 88)
    return code, pred, index


def adpcm_encode_channel(x, block):
    """x: int16 масив одного каналу, довжина кратна block.
    Повертає (заголовки [nb, 4] uint8, напівбайти [nb, block // 2] uint8)."""
    x = x.astype(np.int32).reshape(-1, block)
    nb = x.shape[0]
    # розгін: остання частина попереднього блоку, для першого — тиша
    prev = np.zeros((nb, WARMUP), dtype=np.int32)
    if nb > 1:
        prev[1:] = x[:-1, -WARMUP:]
    pred = prev[:, 0].copy()
    index = np.zeros(nb, dtype=np.int32)
    for i in range(WARMUP):
        _, pred, index = _encode_step(prev[:, i], pred, index)

    head = np.zeros((nb, 4), dtype=np.uint8)
    head[:, 0] = (pred & 0xFF).astype(np.uint8)
    head[:, 1] = ((pred >> 8) & 0xFF).astype(np.uint8)
    head[:, 2] = index.astype(np.uint8)

    codes = np.empty((nb, block), dtype=np.uint8)
    for i in range(block):
        code, pred, index = _encode_step(x[:, i], pred, index)
        codes[:, i] = code
    nib = (codes[:, 0::2] | (codes[:, 1::2] << 4)).astype(np.uint8)
    return head, nib


def adpcm_decode_channel(head, nib, block):
    """Незалежний декодер (для перевірки). Повертає int16 [nb * block]."""
    nb = head.shape[0]
    pred = (head[:, 0].astype(np.int32) | (head[:, 1].astype(np.int32) << 8))
    pred = np.where(pred >= 32768, pred - 65536, pred)
    index = np.minimum(head[:, 2].astype(np.int32), 88)
    codes = np.empty((nb, block), dtype=np.int32)
    codes[:, 0::2] = nib & 0xF
    codes[:, 1::2] = nib >> 4
    out = np.empty((nb, block), dtype=np.int16)
    for i in range(block):
        code = codes[:, i]
        step = STEP[index]
        diff = step >> 3
        diff = diff + np.where(code & 4, step, 0) + np.where(code & 2, step >> 1, 0) \
            + np.where(code & 1, step >> 2, 0)
        pred = np.clip(np.where(code & 8, pred - diff, pred + diff), -32768, 32767)
        index = np.clip(index + INDEX[code], 0, 88)
        out[:, i] = pred
    return out.reshape(-1)


def encode_blocks(pcm, codec, block):
    """pcm: int16 [канали, відліки], довжина кратна block.
    Повертає bytes з усіма блоками та розмір одного блоку в байтах."""
    ch, n = pcm.shape
    nb = n // block
    if codec == 'adpcm':
        parts = [adpcm_encode_channel(pcm[c], block) for c in range(ch)]
        heads = np.concatenate([p[0] for p in parts], axis=1)          # [nb, 4*ch]
        nibs = np.concatenate([p[1] for p in parts], axis=1)           # [nb, ch*block/2]
        blocks = np.concatenate([heads, nibs], axis=1)
    elif codec == 'pcm16':
        per = pcm.reshape(ch, nb, block).transpose(1, 0, 2).astype('<i2')
        blocks = per.reshape(nb, ch * block).view(np.uint8).reshape(nb, ch * block * 2)
    else:
        raise ValueError('невідомий кодек: %s' % codec)
    return np.ascontiguousarray(blocks).tobytes(), blocks.shape[1]


def decode_blocks(raw, codec, channels, block, nblocks):
    """Незалежне розпакування всіх блоків. Повертає int16 [канали, nblocks*block]."""
    a = np.frombuffer(raw, dtype=np.uint8)
    if codec == 'adpcm':
        bb = 4 * channels + channels * block // 2
        a = a[:nblocks * bb].reshape(nblocks, bb)
        out = []
        for c in range(channels):
            head = a[:, 4 * c:4 * c + 4]
            o = 4 * channels + c * block // 2
            out.append(adpcm_decode_channel(head, a[:, o:o + block // 2], block))
        return np.stack(out)
    bb = 2 * channels * block
    a = a[:nblocks * bb].view('<i2').reshape(nblocks, channels, block)
    return a.transpose(1, 0, 2).reshape(channels, -1)
