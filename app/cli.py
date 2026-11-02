# -*- coding: utf-8 -*-
"""Командний рядок (без вікна):

    python app/cli.py make  трек.mp3 --target cpulator|board8|board48 [--codec adpcm|pcm16] [--mono]
    python app/cli.py check файл.elf
    python app/cli.py cpulator файл.elf [--bigmem]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deplayer import make as mk, verify          # noqa: E402
from deplayer.targets import TARGETS             # noqa: E402


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='DE1-SoC audio player')
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('make', help='трек -> файл для плати або CPUlator')
    m.add_argument('track')
    m.add_argument('--target', choices=sorted(TARGETS), default='cpulator')
    m.add_argument('--codec', choices=['adpcm', 'pcm16'], default='adpcm')
    m.add_argument('--mono', action='store_true')
    m.add_argument('--start', type=float, default=0.0)
    m.add_argument('--length', type=float, default=None)
    m.add_argument('--no-normalize', action='store_true')
    m.add_argument('--out', default=None)
    c = sub.add_parser('check', help='перевірити готовий файл')
    c.add_argument('elf')
    r = sub.add_parser('cpulator', help='відкрити CPUlator із завантаженим файлом')
    r.add_argument('elf')
    r.add_argument('--bigmem', action='store_true')
    a = ap.parse_args()

    if a.cmd == 'make':
        res = mk.make(a.track, a.target, a.codec, 1 if a.mono else 2, a.start, a.length,
                      not a.no_normalize, a.out)
        sys.exit(0 if res['ok'] else 1)
    if a.cmd == 'check':
        with open(a.elf, 'rb') as f:
            ok, lines, _ = verify.check(f.read())
        print('\n'.join(lines))
        sys.exit(0 if ok else 1)
    if a.cmd == 'cpulator':
        from deplayer import helper
        h = helper.start(os.path.dirname(os.path.abspath(a.elf)), 192 if a.bigmem else 0)
        url = h.url_for(os.path.basename(a.elf))
        print('CPUlator:', url)
        import webbrowser
        webbrowser.open(url)
        print('Не закривайте це вікно, поки працюєте. Зупинка — Ctrl+C.')
        try:
            h.thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
