# -*- coding: utf-8 -*-
"""Схеми й графіки для README та звіту (чорно-білі, Times New Roman).

    python docs/make_figures.py [трек.mp3]   (без треку — лише схеми)

Потрібні Graphviz (dot), matplotlib і Pillow — лише для цих рисунків, не для застосунку.
"""
import csv
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'app'))
from deplayer import audio, blob                  # noqa: E402
from deplayer.targets import TARGETS              # noqa: E402

import matplotlib                                 # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                   # noqa: E402
from matplotlib.ticker import FuncFormatter       # noqa: E402

plt.rcParams.update({'font.family': 'Times New Roman', 'font.size': 12, 'axes.linewidth': 0.8,
                     'savefig.dpi': 200, 'savefig.bbox': 'tight'})
FONT = 'Times New Roman,'   # кома: інакше Pango сприймає «Roman» як стиль


def num(v, fmt='%g'):
    """Число за ДСТУ: десяткова кома й справжній мінус."""
    return (fmt % v).replace('.', ',').replace('-', '−')


def comma_axes(*axes):
    for ax in axes:
        for a in (ax.xaxis, ax.yaxis):
            a.set_major_formatter(FuncFormatter(lambda v, _: num(round(v, 6))))


def dot(name, src):
    path = os.path.join(HERE, name + '.png')
    subprocess.run(['dot', '-Tpng', '-Gdpi=300', '-o', path], input=src.encode('utf-8'), check=True)
    with Image.open(path) as im:
        print('рисунок %s: %.1f x %.1f см без масштабування' % (
            name, im.width / 300 * 2.54, im.height / 300 * 2.54))


# --------------------------------------------------------------- схеми
def diagram_system():
    dot('diagram_system', r'''
digraph G {
  rankdir=TB; nodesep=0.22; ranksep=0.32; newrank=true;
  node [shape=box, fontname="%s", fontsize=13, style="rounded", margin="0.07,0.04"];
  edge [arrowsize=0.7];
  subgraph cluster_pc { label="Комп'ютер: застосунок audio_player (Python)"; fontname="%s"; fontsize=13; style=dashed;
    trk [label="Трек\nmp3, wav, flac, ogg"];
    dec [label="Розкодування\n(miniaudio)"];
    rs  [label="Зміна частоти до\n8 або 48 кГц (FFT)"];
    { rank=same; trk; dec; rs; }
    trk -> dec -> rs;
    elf [label="ELF: player.elf + сегмент\nтреку 0x00200000"];
    blb [label="Трек «DE1A»: заголовок\n64 Б, контрольна сума"];
    enc [label="IMA ADPCM або PCM16\nблоками по 1024 відліки"];
    { rank=same; elf; blb; enc; }
    elf -> blb [dir=back]; blb -> enc [dir=back];
    rs -> enc;
    ver [label="Перевірка: заголовок, контрольна сума,\nрозпакування всіх блоків, SNR"];
    elf -> ver;
  }
  cpu [label="CPUlator, звук 8 кГц: місцевий\nпосередник, автозавантаження"];
  mp  [label="Intel FPGA Monitor Program\n(JTAG, програма типу ELF)"];
  { rank=same; cpu; mp; }
  ver -> cpu; ver -> mp;
  subgraph cluster_board { label="Плата DE1-SoC, система ЛР5 (8 або 48 кГц)"; labelloc=b; fontname="%s"; fontsize=13; style=dashed;
    key [label="KEY0–KEY3\n0xFF200050"];
    arm [label="ARM Cortex-A9: player.c\nDDR3: програма й трек"];
    aud [label="Звуковий порт\n0xFF203040"];
    { rank=same; key; arm; aud; }
    key -> arm -> aud;
    led [label="LEDR9–LEDR0, 0xFF200000\nшкала гучності"];
    cod [label="Кодек WM8731\nLINE OUT"];
    { rank=same; led; cod; }
    arm -> led; aud -> cod;
  }
  mp -> arm;
}''' % ((FONT,) * 3))


def diagram_states():
    dot('diagram_states', r'''
digraph S {
  rankdir=TB; nodesep=0.45; ranksep=0.5; newrank=true;
  node [shape=ellipse, fontname="%s", fontsize=13, margin="0.03,0.03"];
  edge [fontname="%s", fontsize=12, arrowsize=0.7];
  start [shape=point, width=0.12];
  chk [shape=diamond, label="заголовок і контрольна\nсума правильні?", margin="0,0"];
  BAD [label="ПОМИЛКА\nLEDR блимають\nчерез один", style=dashed];
  { rank=same; chk; BAD; }
  PLAY [label="ВІДТВОРЕННЯ\nчерга доливається,\nшкала гучності"];
  PAUSE [label="ПАУЗА\nчергу очищено,\nшкала блимає"];
  END [label="КІНЕЦЬ\nсвітлодіоди згасли,\nна HEX «En»"];
  { rank=same; PAUSE; END; }
  start -> chk;
  chk -> BAD [label="  ні  "];
  chk -> PLAY [label=" так"];
  PLAY -> PLAY [label="KEY1 — з початку\nKEY2, KEY3 — ±10 с"];
  PLAY -> PAUSE [label="KEY0: позиція\nза годинником  "];
  PAUSE -> PLAY [label="  KEY0 — далі\n  KEY1 — з початку"];
  PAUSE -> PAUSE [label="KEY2, KEY3\n±10 с"];
  PLAY -> END [label="  тишу після треку\n  записано, трек\n  відзвучав"];
  END -> PLAY [label="  KEY0, KEY1 — з початку\n  KEY2 — на 10 с назад"];
}''' % (FONT, FONT))


def diagram_loop():
    dot('diagram_loop', r'''
digraph L {
  rankdir=TB; nodesep=0.3; ranksep=0.24; newrank=true;
  node [shape=box, fontname="%s", fontsize=12, margin="0.08,0.04"];
  edge [arrowsize=0.65, fontname="%s", fontsize=12];
  s [style=rounded, label="Старт: таймер, скидання\nрегістра захоплення KEY"];
  c [shape=diamond, margin="0,0", label="заголовок і\nконтрольна сума\nправильні?"];
  e [label="ПОМИЛКА:\nблимання LEDR\nчерез один", style=dashed];
  { rank=same; c; e; }
  k [shape=diamond, margin="0,0", label="у регістрі\nзахоплення є\nнатискання?"];
  a [label="KEY0: пауза, продовження\nKEY1: з початку\nKEY2, KEY3: ±10 с\n(перехід очищає чергу)"];
  a1 [shape=circle, label="А", margin=0, width=0.34, height=0.34];
  a2 [shape=circle, label="А", margin=0, width=0.34, height=0.34];
  { rank=same; a1; k; a; }
  p [shape=diamond, margin="0,0", label="стан =\nВІДТВОРЕННЯ?"];
  b [label="пауза: блимання шкали\nкінець: LEDR = 0"];
  { rank=same; p; b; }
  f [label="fill_fifo(): доки в черзі є місце, розпакувати\nблок, записати L і R, пік модуля у вікні 20 мс.\nПісля кінця треку записується тиша"];
  u [label="update_clock(): годинник за таймером у межах\nпозиції запису мінус затримка черги"];
  t [label="тишу записано, трек відзвучав: стан = КІНЕЦЬ"];
  m [label="meter_step(): рівень вікна у смугу, спад\n1 світлодіод за 40 мс, утримання піку 0,6 с"];
  h [label="HEX: час мм.сс (лише CPUlator)"];
  s -> c; c -> e [label=" ні "]; c -> k [label=" так"];
  k -> a [label=" так "]; k -> p [label=" ні"]; a -> p;
  p -> b [label=" ні "]; p -> f [label=" так"];
  f -> u -> t -> m -> h;
  b -> h;
  a1 -> k; h -> a2;
}''' % (FONT, FONT))


def diagram_format():
    dot('diagram_format', r'''
digraph F {
  rankdir=TB; nodesep=0.2; ranksep=0.32;
  node [shape=record, fontname="%s", fontsize=13];
  edge [fontname="%s", fontsize=12, arrowsize=0.7];
  elf [label="{ELF для ARM|{заголовок\nELF, 52 Б|заголовки\nпрограми|сегмент 1: програвач\n0x00000000, 6,3 КБ|сегмент 2: трек\n0x00200000|заголовки\nрозділів}}"];
  hdr [label="{Заголовок треку «DE1A», 64 Б|{сигнатура, версія,\nкодек|частота,\nканали|відліків у блоці,\nблоків|байтів у блоці,\nусього відліків}|{зміщення й розмір\nданих|контрольна\nсума|прапорці,\nзатримка черги|вікно шкали,\nmax_lag}}"];
  blk [label="{Блок IMA ADPCM, 1032 Б (стерео)|{стан L, 4 Б\n(pred, index)|стан R, 4 Б\n(pred, index)|L: 1024 напівбайти\n512 Б|R: 1024 напівбайти\n512 Б}}"];
  elf -> hdr [label="  початок сегмента 2"];
  hdr -> blk [label="  далі блоки підряд"];
}''' % (FONT, FONT))


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
    a2.legend(loc='lower center', frameon=False, fontsize=10, ncol=2)
    comma_axes(a1, a2)
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
        ax.plot(x, pcm[0, a:a + n] / 32768, color='black', linewidth=0.9, label='підготовлений звук')
        ax.plot(x, dec[0, a:a + n] / 32768, color='0.45', linewidth=0.9, linestyle='--',
                label='після IMA ADPCM')
        ax.plot(x, (pcm[0, a:a + n].astype(int) - dec[0, a:a + n]) / 32768, color='0.3',
                linewidth=0.6, linestyle=':', label='похибка')
        e = pcm.astype(np.float64) - dec.astype(np.float64)
        snr = 10 * np.log10(np.mean(pcm.astype(np.float64) ** 2) / np.mean(e ** 2))
        out[key] = snr
        ax.set_title('%d Гц, SNR %s дБ' % (t.rate, num(snr, '%.1f')), fontsize=12)
        ax.set_ylabel('Амплітуда')
        comma_axes(ax)
    axes[-1].set_xlabel('t, мс (фрагмент із 60-ї секунди)')
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc='upper center', ncol=3, frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(HERE, 'plot_adpcm.png'))
    plt.close(fig)
    print('рисунок plot_adpcm.png; SNR:', {k: round(v, 1) for k, v in out.items()})
    return out


def plot_clock():
    """Виміряне відхилення годинника шкали від звуку: clock_offset.csv пише
    tests/cpulator_sync.py (спостереження за Web Audio у CPUlator)."""
    with open(os.path.join(HERE, 'clock_offset.csv'), encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    t = [int(r['second']) for r in rows]
    d = [float(r['clock_minus_sound']) for r in rows]
    fig, ax = plt.subplots(figsize=(6.5, 2.7))
    ax.axhline(0, color='0.6', linewidth=0.7, linestyle=':')
    ax.plot(t, d, color='black', linewidth=0.9, marker='o', markersize=3)
    ax.set_xlabel('Час на індикаторах, с')
    ax.set_ylabel('Годинник мінус звук, с')
    comma_axes(ax)
    fig.savefig(os.path.join(HERE, 'plot_clock.png'))
    plt.close(fig)
    print('рисунок plot_clock.png: %+.2f…%+.2f с' % (min(d), max(d)))


if __name__ == '__main__':
    diagram_system()
    diagram_states()
    diagram_loop()
    diagram_format()
    if len(sys.argv) < 2:
        sys.exit(0)
    track = sys.argv[1]
    pcm, _ = audio.prepare(track, 8000, 2)
    plot_meter(pcm, 8000)
    plot_adpcm(track)
    plot_clock()
