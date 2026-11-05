# -*- coding: utf-8 -*-
"""Збіг програвача зі звуком у CPUlator: python tests/cpulator_sync.py файл.elf [вихід.csv]

Спостерігає за Web Audio на сторінці симулятора: коли браузер запланував кожен блок
звуку. Порівнює з цим час на індикаторах і момент появи «En». Потрібен файл для
CPUlator (на платі індикаторів немає), інтернет і Chrome або Edge.
"""
import csv
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
from deplayer import cdp, check, helper   # noqa: E402

HOOK = r"""
window.__au = []; window.__ctx = null;
const start0 = AudioBufferSourceNode.prototype.start;
AudioBufferSourceNode.prototype.start = function (when) {
  window.__ctx = this.context;
  const d = this.buffer.getChannelData(0); let last = -1;
  for (let i = d.length - 1; i >= 0; i--) if (d[i] !== 0) { last = i; break; }
  window.__au.push({when: when || this.context.currentTime, now: this.context.currentTime,
                    rate: this.buffer.sampleRate, last: last});
  return start0.apply(this, arguments);
};
return 1;
"""
POLL = """return {h: [...document.querySelectorAll('#devff200020 .dev_sseg')].filter(d=>d.offsetParent!==null)
  .map(d=>[...d.children].reduce((v,c,i)=>v|(c.classList.contains('dev_sseg_off')?0:1<<i),0)),
  c: (window.__ctx ? window.__ctx.currentTime : -1), f: (window.__au[0] ? window.__au[0].when : null)};"""


def measure(elf_path):
    """Повертає (список (секунда на індикаторах, годинник мінус звук), En мінус кінець звуку)."""
    hdr = check._track_header(elf_path)
    limit = hdr['total_samples'] / hdr['rate'] + 15
    h = helper.start(os.path.dirname(os.path.abspath(elf_path)), 0)
    b = cdp.Browser(h.url_for(os.path.basename(elf_path)))
    try:
        for _ in range(240):
            if 'Total size' in (b.js(check.MSG) or ''):
                break
            time.sleep(0.5)
        b.js(HOOK)
        c = b.rect("[...document.querySelectorAll('button')].find(x=>x.textContent.trim().startsWith('Continue'))")
        b.click(c['x'] + c['w'] / 2, c['y'] + c['h'] / 2)
        t0, prev, points, en_ctx = time.time(), None, [], None
        while time.time() - t0 < limit:
            r = b.js(POLL)
            shown = ''.join(check.SEG7.get(v & 0x7F, '?') for v in r['h'])
            if shown[:2] == 'En':
                en_ctx = r['c']
                break
            cur = shown[-4:]
            if prev is not None and cur != prev and cur.isdigit() and r['f'] is not None:
                sec = int(cur[:2]) * 60 + int(cur[2:])
                points.append((sec, sec - (r['c'] - r['f'])))
            prev = cur
            time.sleep(0.005)
        time.sleep(1.0)
        blocks = b.js('return window.__au;') or []
        loud = [a for a in blocks if a['last'] >= 0]
        end = loud[-1]['when'] + (loud[-1]['last'] + 1) / loud[-1]['rate']
        return points, (en_ctx - end) if en_ctx is not None else None
    finally:
        b.close()
        h.stop()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    points, en = measure(sys.argv[1])
    steady = [d for s, d in points if s >= 8]
    if steady:
        print('годинник мінус звук після 8-ї секунди: %+.2f…%+.2f с, у середньому %+.2f с'
              % (min(steady), max(steady), sum(steady) / len(steady)))
    print('на перших секундах:', ' '.join('%+.2f' % d for s, d in points if s < 8))
    print('«En» відносно кінця звуку: %s' % ('не з\'явилося' if en is None else '%+.3f с' % en))
    if len(sys.argv) > 2:
        with open(sys.argv[2], 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['second', 'clock_minus_sound'])
            for s, d in points:
                w.writerow([s, '%.3f' % d])
    return 0 if en is not None else 1


if __name__ == '__main__':
    sys.exit(main())
