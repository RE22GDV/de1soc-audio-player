# -*- coding: utf-8 -*-
"""Перевірка заголовка треку на комп'ютері: python -m unittest discover tests"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
from deplayer import blob                         # noqa: E402
from deplayer.targets import BLOCK, TARGETS       # noqa: E402


def make_header(codec='adpcm', target='cpulator', samples=2500, channels=2):
    t = np.arange(samples) / 8000
    tone = (8000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    raw, _ = blob.build(np.tile(tone, (channels, 1)), codec, TARGETS[target])
    return blob.parse(raw)


class HeaderErrors(unittest.TestCase):
    def test_built_tracks_have_no_errors(self):
        for codec in ('adpcm', 'pcm16'):
            for target in TARGETS:
                for channels in (1, 2):
                    h = make_header(codec, target, channels=channels)
                    self.assertEqual(blob.header_errors(h), [], (codec, target, channels))

    def test_every_inconsistent_field_is_reported(self):
        good = make_header()
        cases = {
            'magic': b'XXXX',
            'version': 2,
            'codec': 7,
            'rate': 44100,
            'channels': 3,
            'block_samples': 4096,
            'block_bytes': good['block_bytes'] + 2,
            'blocks': good['blocks'] + 1,
            'total_samples': good['blocks'] * BLOCK + 1,
            'data_off': 128,
            'data_size': good['data_size'] + 4,
            'meter_win': 0,
            'latency': 1 << 20,
            'max_lag': 1 << 20,
            'flags': 0x80,
        }
        for field, value in cases.items():
            h = dict(good, **{field: value})
            self.assertTrue(blob.header_errors(h), field)

    def test_total_samples_must_reach_the_last_block(self):
        good = make_header()
        h = dict(good, total_samples=(good['blocks'] - 1) * BLOCK)
        self.assertTrue(blob.header_errors(h))
        h = dict(good, total_samples=(good['blocks'] - 1) * BLOCK + 1)
        self.assertEqual(blob.header_errors(h), [])

    def test_data_outside_ddr3_is_reported(self):
        h = dict(make_header(), data_size=0xFFFFFFF0)
        self.assertTrue(any('DDR3' in e for e in blob.header_errors(h)))

    def test_odd_adpcm_block_is_reported(self):
        h = dict(make_header(), block_samples=1023)
        self.assertTrue(blob.header_errors(h))


if __name__ == '__main__':
    unittest.main()
