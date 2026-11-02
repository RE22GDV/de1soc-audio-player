# -*- coding: utf-8 -*-
"""Схеми й графіки для README та звіту (чорно-білі, Times New Roman).

    python docs/make_figures.py трек.mp3

Потрібні Graphviz (dot) і matplotlib — лише для цих рисунків, не для застосунку.
"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'app'))
from deplayer import audio, blob                  # noqa: E402
from deplayer.targets import TARGETS              # noqa: E402

import matplotlib                                 # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                   # noqa: E402

plt.rcParams.update({'font.family': 'Times New Roman', 'font.size': 12, 'axes.linewidth': 0.8,
                     'savefig.dpi': 200, 'savefig.bbox': 'tight'})
FONT = 'Times New Roman,'   # кома: інакше Pango сприймає «Roman» як стиль


def dot(name, src):
    path = os.path.join(HERE, name + '.png')
    subprocess.run(['dot', '-Tpng', '-Gdpi=300', '-o', path], input=src.encode('utf-8'), check=True)
    print('рисунок', path)


# --------------------------------------------------------------- схеми
def diagram_system():
    dot('diagram_system', r'''
digraph G {
  rankdir=TB; nodesep=0.3; ranksep=0.45; newrank=true;
  node [shape=box, fontname="%s", fontsize=12, style="rounded"];
  edge [fontname="%s", fontsize=10, arrowsize=0.7];
  subgraph cluster_pc { label="Комп'ютер: застосунок audio_player (Python)"; fontname="%s"; fontsize=12; style=dashed;
    trk [label="Трек
mp3 / wav / flac"];
    dec [label="Розкодування
(miniaudio)"];
    rs  [label="Зміна частоти
до 8 або 48 кГц (FFT)"];
    enc [label="IMA ADPCM або PCM16
блоками по 1024 відліки"];
    blb [label="Трек «DE1A»: заголовок
64 Б, контрольна сума"];
    elf [label="ELF: player.elf +
сегмент треку 0x00200000"];
    ver [label="Перевірка: розпакування,
SNR, контрольна сума"];
    { rank=same; trk; dec; rs; enc; }
    { rank=same; blb; elf; ver; }
    trk -> dec -> rs -> enc;
    enc -> blb; blb -> elf -> ver;
  }
  cpu [label="CPUlator, звук 8000 Гц:
місцевий посередник —
автозавантаження й пам'ять"];
  mp  [label="Intel FPGA Monitor Program
(JTAG, програма типу ELF)"];
  { rank=same; cpu; mp; }
  subgraph cluster_board { label="Плата DE1-SoC, система ЛР5 (8 або 48 кГц)"; labelloc=b; fontname="%s"; fontsize=12; style=dashed;
    key [label="KEY0–KEY3
0xFF200050"];
    arm [label="ARM Cortex-A9: player.c
DDR3: код + трек"];
    aud [label="Audio core
0xFF203040"];
    cod [label="Кодек WM8731
LINE OUT"];
    led [label="LEDR9–LEDR0 0xFF200000
шкала гучності"];
    { rank=same; key; arm; aud; cod; }
    key -> arm -> aud -> cod;
    arm -> led;
  }
  ver -> cpu; ver -> mp; mp -> arm;
}''' % ((FONT,) * 4))


def diagram_states():
    dot('diagram_states', r'''
digraph S {
  rankdir=LR; nodesep=0.6; ranksep=0.9;
  node [shape=ellipse, fontname="%s", fontsize=12];
  edge [fontname="%s", fontsize=10, arrowsize=0.7];
  start [shape=point, width=0.12];
  chk [shape=diamond, label="контрольна\nсума збігається?", fontsize=11];
  PLAY [label="ВІДТВОРЕННЯ\nчерга звуку доливається,\nшкала гучності"];
  PAUSE [label="ПАУЗА\nчергу очищено,\nшкала блимає"];
  END [label="КІНЕЦЬ\nсвітлодіоди згасли"];
  BAD [label="ПОМИЛКА\nLEDR блимають\nчерез один", style=dashed];
  start -> chk;
  chk -> PLAY [label="так"];
  chk -> BAD [label="ні"];
  PLAY -> PAUSE [label="KEY0\n(запам'ятати позицію)"];
  PAUSE -> PLAY [label="KEY0\n(з тієї ж позиції)"];
  PLAY -> END [label="трек дограв"];
  END -> PLAY [label="KEY0 або KEY1\n(з початку)"];
  PLAY -> PLAY [label="KEY1 — з початку\nKEY2/KEY3 — ±10 с"];
  PAUSE -> PLAY [label="KEY1"];
}''' % (FONT, FONT))


def diagram_loop():
    dot('diagram_loop', r'''
digraph L {
  rankdir=TB; nodesep=0.3; ranksep=0.28;
  node [shape=box, fontname="%s", fontsize=11];
  edge [arrowsize=0.6, fontname="%s", fontsize=10];
  s [shape=box, style=rounded, label="Старт: таймер, скидання\nрегістра захоплення KEY"];
  c [shape=diamond, label="заголовок і\nконтрольна сума\nправильні?"];
  e [label="ПОМИЛКА:\nблимання LEDR", style=dashed];
  k [shape=diamond, label="у регістрі\nзахоплення є\nнатискання?"];
  a [label="KEY0 пауза / продовження\nKEY1 з початку\nKEY2, KEY3 ±10 с\n(seek: очистити чергу)"];
  p [shape=diamond, label="стан =\nВІДТВОРЕННЯ?"];
  f [label="fill_fifo(): доки в черзі є місце —\nрозпакувати блок, записати L/R,\nпік модуля у вікні 20 мс"];
  u [label="update_clock(): годинник за таймером,\nобмежений pos − затримка черги"];
  m [label="meter_step(): рівень вікна → смуга,\nспад 1 світлодіод за 40 мс,\nутримання піку 0,6 с → LEDR"];
  b [label="блимання шкали (пауза)\nабо LEDR = 0 (кінець)"];
  h [label="HEX: час мм.сс (лише CPUlator)"];
  s -> c; c -> e [label="ні"]; c -> k [label="так"];
  k -> a [label="так"]; k -> p [label="ні"]; a -> p;
  p -> f [label="так"]; f -> u -> m -> h;
  p -> b [label="ні"]; b -> h;
  h -> k [constraint=false, label="  цикл"];
}''' % (FONT, FONT))


def diagram_format():
    dot('diagram_format', r'''
digraph F {
  rankdir=TB; nodesep=0.2; ranksep=0.35;
  node [shape=record, fontname="%s", fontsize=11];
  elf [label="{ELF для ARM|{заголовок ELF\n52 Б|заголовки\nпрограми|сегмент 1:\nплеєр, 0x00000000\n~5,8 КБ|сегмент 2:\nтрек, 0x00200000|заголовки\nрозділів}}"];
  hdr [label="{Заголовок треку «DE1A», 64 Б|{magic|версія\nкодек|частота|канали\nвідліків у блоці|блоків\nбайтів у блоці|відліків|зміщення\nрозмір даних|контрольна\nсума|прапорці\n(HEX)|затримка\nчерги|вікно шкали\nmax_lag}}"];
  blk [label="{Блок IMA ADPCM, 1032 Б (стерео)|{стан L: 4 Б\n(pred, index)|стан R: 4 Б|L: 1024 напівбайти\n512 Б|R: 1024 напівбайти\n512 Б}}"];
  elf -> hdr [label="початок сегмента 2", fontname="%s", fontsize=10, arrowsize=0.6];
  hdr -> blk [label="далі блоки підряд", fontname="%s", fontsize=10, arrowsize=0.6];
}''' % ((FONT,) * 3))


# --------------------------------------------------------------- графіки
THR_DB = [-39, -33, -28, -24, -20, -16, -12, -9, -6, -3]


def leds_model(pcm, rate):
    """Те саме, що робить програвач: пік за 20 мс -> рівень 0..10 -> смуга зі спадом і піком."""
    win = rate // 50
    n = pcm.shape[1] // win
    peak = np.abs(pcm[:, :n * win].astype(np.int32)).reshape(pcm.shape[0], n, win).max(axis=(0, 2))
    thr = np.round(32767 * 10 ** (np.array(THR_DB) / 20)).astype(np.int32)
    lvl = (peak[:, None] >= thr[None, :]).sum(axis=1)
    bar = np.zeros(n, dtype=int)
    hold = np.zeros(n, dtype=int)
    b = h = 0
    fall = hl = 2
    for i, v in enumerate(lvl):
        if v >= b:
            b, fall = v, 2
        else:
            fall -= 1
            if fall <= 0:
                b, fall = b - 1, 2
        if v >= h:
            h, hl = v, 30
        else:
            hl -= 1
            if hl <= 0 and h > 0:
                h, hl = h - 1, 3
        bar[i], hold[i] = b, h
    return peak, lvl, bar, hold, win


def plot_meter(pcm, rate):
    peak, lvl, bar, hold, win = leds_model(pcm, rate)
    t = np.arange(len(peak)) * win / rate
    db = 20 * np.log10(np.maximum(peak, 1) / 32768)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 4.6), sharex=True,
                                 gridspec_kw={'height_ratios': [1.1, 1]})
    a1.plot(t, db, color='black', linewidth=0.4)
    for d in THR_DB:
        a1.axhline(d, color='0.6', linewidth=0.4, linestyle=':')
    a1.set_ylim(-45, 1)
    a1.set_ylabel('Пік за 20 мс, дБ')
    a2.step(t, bar, where='post', color='black', linewidth=0.6, label='смуга')
    a2.plot(t, hold, color='0.45', linewidth=0.6, linestyle='--', label='утримання піку')
    a2.set_ylim(-0.3, 10.3)
    a2.set_yticks(range(0, 11, 2))
    a2.set_ylabel('Світлодіодів')
    a2.set_xlabel('t, с')
    a2.legend(loc='lower right', frameon=False, fontsize=10)
    fig.savefig(os.path.join(HERE, 'plot_meter.png'))
    plt.close(fig)
    hist = np.bincount(bar, minlength=11) / len(bar) * 100
    print('рисунок plot_meter.png; частка часу за кількістю світлодіодів, %:', np.round(hist, 1))
    return hist


def plot_adpcm(track):
    out = {}
    fig, axes = plt.subplots(2, 1, figsize=(6.5, 4.6))
    for ax, key in zip(axes, ('cpulator', 'board48')):
        t = TARGETS[key]
        pcm, _ = audio.prepare(track, t.rate, 2)
        raw, _ = blob.build(pcm, 'adpcm', t)
        dec = blob.decode(raw)
        a = int(60.0 * t.rate)
        n = int(0.020 * t.rate)
        x = np.arange(n) / t.rate * 1000
        ax.plot(x, pcm[0, a:a + n] / 32768, color='black', linewidth=0.9, label='вихідний звук')
        ax.plot(x, dec[0, a:a + n] / 32768, color='0.45', linewidth=0.9, linestyle='--',
                label='після IMA ADPCM')
        ax.plot(x, (pcm[0, a:a + n].astype(int) - dec[0, a:a + n]) / 32768, color='0.3',
                linewidth=0.6, linestyle=':', label='похибка')
        e = pcm.astype(np.float64) - dec.astype(np.float64)
        snr = 10 * np.log10(np.mean(pcm.astype(np.float64) ** 2) / np.mean(e ** 2))
        out[key] = snr
        ax.set_title('%d Гц, SNR %.1f дБ' % (t.rate, snr), fontsize=12)
        ax.set_ylabel('Амплітуда')
        ax.legend(loc='upper right', frameon=False, fontsize=9, ncol=3)
    axes[-1].set_xlabel('t, мс (фрагмент із 60-ї секунди)')
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, 'plot_adpcm.png'))
    plt.close(fig)
    print('рисунок plot_adpcm.png; SNR:', {k: round(v, 1) for k, v in out.items()})
    return out


def plot_clock():
    """Модель годинника шкали в CPUlator: черга 8192 відліки знімається блоками
    по 2048 щочетверть секунди й одразу доливається, таймер іде на 95,65 %
    реального часу. Що звучить: блок, знятий з черги, грає наступні 256 мс."""
    t_ = TARGETS['cpulator']
    rate, lat, lag = t_.rate, t_.latency, t_.max_lag
    dt = 0.002
    T = np.arange(0, 2.5, dt)
    deq, clk = 0, 0
    P, C, H, L = [], [], [], []
    for t in T:
        k = int(t / 0.256) + 1              # скільки блоків уже знято з черги
        deq = 2048 * k
        pos = deq + 8192                    # програвач одразу доливає чергу
        heard = max(0.0, 2048 * (k - 1) + (t % 0.256) * rate)
        clk += rate * dt * 0.9565
        hi = pos - lat
        lo = hi - lag
        clk = min(max(clk, lo), hi)
        P.append(heard)
        C.append(clk)
        H.append(hi)
        L.append(lo)
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    ax.fill_between(T, np.array(L) / rate, np.array(H) / rate, color='0.88', step='pre',
                    label='дозволене вікно годинника')
    ax.plot(T, np.array(C) / rate, color='black', linewidth=1.2, label='годинник шкали clk')
    ax.plot(T, np.array(P) / rate, color='0.3', linewidth=0.9, linestyle='--', label='що звучить')
    ax.set_xlabel('Час роботи, с')
    ax.set_ylabel('Позиція в треку, с')
    ax.set_ylim(bottom=0)
    ax.legend(loc='upper left', frameon=False, fontsize=10)
    fig.savefig(os.path.join(HERE, 'plot_clock.png'))
    plt.close(fig)
    err = np.array(C[400:]) - np.array(P[400:])
    print('рисунок plot_clock.png; відхилення годинника від звучання: %.0f…%.0f мс'
          % (err.min() / rate * 1000, err.max() / rate * 1000))


if __name__ == '__main__':
    track = sys.argv[1]
    diagram_system()
    diagram_states()
    diagram_loop()
    diagram_format()
    pcm, _ = audio.prepare(track, 8000, 2)
    plot_meter(pcm, 8000)
    plot_adpcm(track)
    plot_clock()
