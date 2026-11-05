# -*- coding: utf-8 -*-
"""Читання треку на комп'ютері: python -m unittest discover tests"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
from deplayer import audio                        # noqa: E402

RATE = 44100
SECONDS = 1


def write_tone(path, rate=RATE):
    t = np.arange(rate * SECONDS) / rate
    tone = (12000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(tone.tobytes())


class ReadTrack(unittest.TestCase):
    def check_path(self, folder, name):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, folder)
            os.makedirs(d)
            path = os.path.join(d, name)
            write_tone(path)
            x, sr, duration = audio.load(path)
            self.assertEqual(sr, RATE)
            self.assertEqual(x.shape, (1, RATE * SECONDS))
            self.assertAlmostEqual(duration, SECONDS, places=3)
            pcm, note = audio.prepare(path, 8000, 2)
            self.assertEqual(pcm.shape, (2, 8000 * SECONDS))
            self.assertAlmostEqual(note['source_seconds'], SECONDS, places=3)

    def test_ascii_path(self):
        self.check_path('music', 'track.wav')

    def test_cyrillic_folder(self):
        self.check_path('9 сем', 'track.wav')

    def test_cyrillic_name(self):
        self.check_path('music', 'Неможлива мрія.wav')

    def test_file_keeps_its_own_rate_and_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'track.wav')
            write_tone(path, rate=48000)
            x, sr, _ = audio.load(path)
            self.assertEqual(sr, 48000)
            self.assertEqual(x.shape, (1, 48000 * SECONDS))

    def test_source_channels_are_reported_before_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'track.wav')
            write_tone(path)
            _, note = audio.prepare(path, 8000, 2)
            self.assertEqual(note['source_channels'], 1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'потрібен ffmpeg, щоб створити файли')
    def test_every_format_from_cyrillic_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, '9 сем')
            os.makedirs(d)
            wav = os.path.join(tmp, 'tone.wav')
            write_tone(wav)
            for ext in ('mp3', 'flac', 'ogg'):
                path = os.path.join(d, 'Неможлива мрія.' + ext)
                subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', wav, path], check=True)
                x, sr, duration = audio.load(path)
                self.assertEqual(sr, RATE, ext)
                self.assertEqual(x.shape[0], 1, ext)
                self.assertAlmostEqual(duration, SECONDS, delta=0.1, msg=ext)

    def test_not_audio_gives_a_clear_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'track.mp3')
            with open(path, 'wb') as f:
                f.write(b'not audio at all' * 100)
            with self.assertRaisesRegex(ValueError, 'Підтримуються mp3'):
                audio.load(path)

    def test_missing_file_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            audio.load(os.path.join(tempfile.gettempdir(), 'немає такого файла.mp3'))


if __name__ == '__main__':
    unittest.main()
