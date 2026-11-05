# -*- coding: utf-8 -*-
"""Автоматична перевірка файла в CPUlator (браузер без вікна).

Завантажує файл, запускає програвач і дивиться на те саме, що побачила б
людина: чи світиться й рухається шкала на LEDR, чи наповнюється черга
звуку без спустошень, чи працюють KEY0 (пауза) і KEY1 (з початку), чи
доходить трек до кінця.
"""
import os
import re
import time

from . import blob as blobmod
from . import cdp, elf, helper

LEDS = r"""return [...document.querySelectorAll('#devff200000 .dev_led_led')].filter(d=>d.offsetParent!==null)
  .map(d=>{const m=getComputedStyle(d).backgroundColor.match(/\d+/g); return (m && +m[0]>200 && +m[1]<120)?'1':'0';}).join('');"""
AUDIO = "const e=document.getElementById('devff203040'); return e ? e.innerText.replace(/\\s+/g,' ') : '';"
MSG = r"""return (((document.body && document.body.innerText)||'').match(/Total size is \d+ bytes/)||[''])[0];"""
STATE = "return (document.getElementById('tb_runstate')||{}).textContent||'';"
BANNER = "return (document.getElementById('de1a_banner')||{}).textContent||'';"
# сегменти кожного індикатора як число: a — розряд 0, ... g — розряд 6, крапка — розряд 7
HEX = r"""return [...document.querySelectorAll('#devff200020 .dev_sseg')].filter(d=>d.offsetParent!==null)
  .map(d=>[...d.children].reduce((v,c,i)=>v|(c.classList.contains('dev_sseg_off')?0:1<<i),0));"""
SEG7 = {0x3F: '0', 0x06: '1', 0x5B: '2', 0x4F: '3', 0x66: '4', 0x6D: '5', 0x7D: '6', 0x07: '7',
        0x7F: '8', 0x6F: '9', 0x73: 'P', 0x77: 'A', 0x79: 'E', 0x54: 'n', 0x00: ' '}
SIM_RATE = 8000       # частота звуку в CPUlator
KEY_SECONDS = 0.55    # скільки триває одне натискання через сторінку, с
MIN_SECONDS = 12      # стільки звучання в CPUlator потрібно, щоб пройти всі перевірки


def _key(b, n):
    """Натиснути й відпустити кнопку KEYn (позначка в панелі Push buttons)."""
    expr = ("[...document.getElementById('devff200050').querySelectorAll('input[type=checkbox]')]"
            ".find(x=>x.getBoundingClientRect().width>0 && (x.parentElement.textContent||'').trim()==='%d')" % n)
    for _ in range(2):
        r = b.rect(expr)
        b.click(r['x'] + r['w'] / 2, r['y'] + r['h'] / 2)
        time.sleep(0.25)


def _out_level(text):
    m = re.search(r'Out L:\s*(\d+)', text)
    return int(m.group(1)) if m else None


def read_hex(b):
    """Рядок на індикаторах, зліва направо (HEX5...HEX0)."""
    return ''.join(SEG7.get(v & 0x7F, '?') for v in (b.js(HEX) or []))


def _track_header(elf_path):
    with open(elf_path, 'rb') as f:
        t = elf.read(f.read())
    base = t['symbols']['__blob_base']
    return blobmod.parse(next(s for s in t['segments'] if s['vaddr'] == base)['data'])


def check_end(b, hdr):
    """Перемотує майже до кінця, чекає на кінець треку й запускає трек знову.
    Повертає (успіх, опис). Світлодіоди можуть згаснути й від тиші, тому ознакою
    кінця є KEY0: у стані КІНЕЦЬ він починає трек заново, а не ставить на паузу."""
    dur = hdr['total_samples'] / hdr['rate']
    slow = hdr['rate'] / SIM_RATE              # файл на 48 кГц у CPUlator звучить ушестеро повільніше
    step = 10 + KEY_SECONDS / slow
    for _ in range(max(0, int((dur - 8) / step))):
        _key(b, 3)
    t0, drained, ended = time.time(), None, False
    has_hex = hdr['flags'] & blobmod.FLAG_HEX != 0
    limit = (step + 8) * slow + 8
    while time.time() - t0 < limit:
        lv = _out_level(b.js(AUDIO))
        en = has_hex and read_hex(b)[:2] == 'En'
        if lv == 0:
            drained = drained or time.time()
            ended = en or not has_hex
            if ended and time.time() - drained > 1.0:
                break
        else:
            drained = None
        time.sleep(0.1)
    if not (drained and ended):
        return False, 'трек не дійшов до кінця за %.0f с (на індикаторах «%s»)' % (limit, read_hex(b))
    leds = b.js(LEDS) or ''
    if '1' in leds:
        return False, 'після кінця треку світлодіоди світяться: ' + leds
    _key(b, 0)
    time.sleep(1.0)
    lv = _out_level(b.js(AUDIO))
    if not lv:
        return False, 'після кінця треку KEY0 не запустив його знову'
    return True, 'кінець треку: LEDR згасли, черга порожня, KEY0 запустив трек знову'


def watch(b, seconds, step=0.05):
    leds, levels, t0 = [], [], time.time()
    while time.time() - t0 < seconds:
        leds.append(b.js(LEDS))
        lv = _out_level(b.js(AUDIO))
        if lv is not None:
            levels.append(lv)
        time.sleep(step)
    return leds, levels


def run(elf_path, bigmem=False, log=print, shot=None):
    """Повертає (успіх, рядки звіту, числа)."""
    lines, nums, ok = [], {}, True

    def res(good, text):
        nonlocal ok
        ok = ok and good
        lines.append(('OK  ' if good else 'НІ  ') + text)
        log(lines[-1])

    h = helper.start(os.path.dirname(os.path.abspath(elf_path)), 192 if bigmem else 0)
    b = None
    try:
        log('Запускаю CPUlator без вікна%s...' % (' з наперед виділеною пам\'яттю' if bigmem else ''))
        b = cdp.Browser(h.url_for(os.path.basename(elf_path)))
        msg = ''
        for attempt in range(2):                             # другий шанс — перезавантажити сторінку
            for _ in range(120):
                try:
                    msg = b.js(MSG) or ''
                except RuntimeError:                         # сторінка ще вантажиться
                    msg = ''
                if 'Total size' in msg:
                    break
                time.sleep(0.5)
            if 'Total size' in msg:
                break
            log('  файл не з’явився за 60 с (%s), перезавантажую сторінку...' % (b.js(BANNER) or 'без банера'))
            b.call('Page.reload', ignoreCache=True)
            time.sleep(2)
        res('Total size' in msg, 'файл завантажено: ' + (msg.strip()[-60:] or 'немає відповіді'))
        if 'Total size' not in msg:
            return False, lines, nums
        hdr = _track_header(elf_path)
        if hdr['total_samples'] / SIM_RATE < MIN_SECONDS:
            res(False, 'фрагмент надто короткий для перевірки: у CPUlator потрібно щонайменше %d с звучання'
                % MIN_SECONDS)
            return False, lines, nums
        c = b.rect("[...document.querySelectorAll('button')].find(x=>x.textContent.trim().startsWith('Continue'))")
        b.click(c['x'] + c['w'] / 2, c['y'] + c['h'] / 2)
        time.sleep(1.0)
        res('Running' in (b.js(STATE) or ''), 'програвач запущено')

        leds, levels = watch(b, 4.0)
        changes = sum(1 for a, c2 in zip(leds, leds[1:]) if a != c2)
        lit = max((x.count('1') for x in leds), default=0)
        nums.update(led_changes=changes, led_max=lit,
                    fifo_avg=sum(levels) / len(levels) if levels else 0,
                    fifo_min=min(levels) if levels else 0, fifo_max=max(levels) if levels else 0)
        res(changes >= 3 and lit >= 3, 'шкала гучності рухається: %d змін за 4 с, до %d світлодіодів' % (changes, lit))
        res(bool(levels) and min(levels) > 0,
            'черга звуку не спорожнюється: %d…%d відліків' % (nums['fifo_min'], nums['fifo_max']))
        res('Overflowed: yes' not in (b.js(AUDIO) or ''), 'запис без переповнення черги (немає ознаки Overflowed)')
        if shot:
            b.shot(shot)

        _key(b, 0)                                           # пауза
        time.sleep(0.6)
        leds_p, levels_p = watch(b, 2.0)
        blinking = len(set(leds_p)) == 2 and '0000000000' in leds_p
        res(blinking and (not levels_p or max(levels_p) == 0),
            'KEY0 — пауза: черга звуку порожня, шкала блимає')
        _key(b, 0)                                           # продовження
        time.sleep(1.0)
        leds_r, levels_r = watch(b, 2.0)
        res(sum(1 for a, c2 in zip(leds_r, leds_r[1:]) if a != c2) >= 3 and bool(levels_r) and levels_r[-1] > 0,
            'KEY0 ще раз — відтворення продовжилося')
        _key(b, 1)                                           # з початку
        time.sleep(1.5)
        res('Running' in (b.js(STATE) or ''), 'KEY1 — трек почався знову')
        res(*check_end(b, hdr))
        return ok, lines, nums
    except Exception as e:
        res(False, 'перевірка зупинилася: %s' % e)
        return False, lines, nums
    finally:
        if b:
            b.close()
        h.stop()
