# -*- coding: utf-8 -*-
"""DE1-SoC Audio Player — вікно застосунку.

Обираєте трек -> застосунок робить файл для плати DE1-SoC або CPUlator,
сам його перевіряє, а за потреби відкриває CPUlator із уже завантаженим
треком (зокрема з наперед виділеною пам'яттю для великих файлів).
"""
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deplayer import __version__                 # noqa: E402
from deplayer import helper                      # noqa: E402
from deplayer.make import ROOT, make             # noqa: E402
from deplayer.targets import TARGETS             # noqa: E402

BOARD_STEPS = """ЯК ЗАПУСТИТИ НА ПЛАТІ DE1-SoC

1. Прошийте ПЛІС системою з лабораторної роботи 5:
     8 кГц  — основний проєкт (вхід із мікрофона), DE1_SoC_Computer.sof;
     48 кГц — варіант LINE IN (тека 1_quartus_project_linein).
   Частота треку має збігатися з частотою системи — її обирають у пункті «Куди».

2. Intel FPGA Monitor Program -> File -> New Project:
     архітектура ARM Cortex-A9;
     система <Custom System>: Computer_System.sopcinfo і DE1_SoC_Computer.sof
     з тієї самої теки проєкту, Preloader — DE1-SoC;
     тип програми — «AXF, ELF or SREC File», файл — згенерований .elf
     (якщо Monitor Program його не прийме — той самий трек у .srec);
     термінал — будь-який, програвач ним не користується.

3. Actions -> Download System (якщо ПЛІС ще не прошито),
   потім Actions -> Load. Великий трек вантажиться через JTAG
   до хвилини. Потім Actions -> Continue (F3).

4. Навушники або колонки — у зелене гніздо LINE OUT.

Керування:
   KEY0 — пауза / продовження (після кінця треку — заново)
   KEY1 — з початку
   KEY2 / KEY3 — на 10 с назад / уперед
   LEDR9..LEDR0 — шкала рівня гучності з утриманням піку;
   на паузі шкала блимає.

Якщо всі світлодіоди блимають через один — трек у пам'яті битий
або не завантажився: програвач перевіряє контрольну суму перед стартом.
"""


class App:
    def __init__(self, root):
        self.root = root
        root.title('DE1-SoC Audio Player %s' % __version__)
        root.geometry('900x700')
        root.minsize(760, 560)
        self.q = queue.Queue()
        self.busy = False
        self.result = None
        self.helper = None

        style = ttk.Style()
        try:
            style.theme_use('vista')
        except tk.TclError:
            pass
        pad = {'padx': 8, 'pady': 4}

        head = ttk.Label(root, text='Трек -> файл для плати DE1-SoC або CPUlator',
                         font=('Segoe UI', 13, 'bold'))
        head.pack(anchor='w', padx=10, pady=(10, 4))

        f1 = ttk.LabelFrame(root, text=' 1. Трек ')
        f1.pack(fill='x', **pad)
        self.track = tk.StringVar()
        ttk.Entry(f1, textvariable=self.track, state='readonly').pack(side='left', fill='x', expand=True,
                                                                       padx=6, pady=6)
        ttk.Button(f1, text='Обрати…', command=self.pick).pack(side='left', padx=6)

        f2 = ttk.LabelFrame(root, text=' 2. Куди і як ')
        f2.pack(fill='x', **pad)
        self.target = tk.StringVar(value='cpulator')
        col = ttk.Frame(f2)
        col.grid(row=0, column=0, sticky='nw', padx=6, pady=4)
        for k, t in TARGETS.items():
            ttk.Radiobutton(col, text=t.title, value=k, variable=self.target).pack(anchor='w')
        col2 = ttk.Frame(f2)
        col2.grid(row=0, column=1, sticky='nw', padx=20, pady=4)
        self.codec = tk.StringVar(value='adpcm')
        ttk.Radiobutton(col2, text='IMA ADPCM (стиснення 4:1)', value='adpcm',
                        variable=self.codec).pack(anchor='w')
        ttk.Radiobutton(col2, text='PCM16 (без втрат, файл учетверо більший)', value='pcm16',
                        variable=self.codec).pack(anchor='w')
        self.mono = tk.BooleanVar(value=False)
        ttk.Checkbutton(col2, text='Моно (файл удвічі менший)', variable=self.mono).pack(anchor='w')
        self.norm = tk.BooleanVar(value=True)
        ttk.Checkbutton(col2, text='Вирівняти гучність (пік −1 дБ)', variable=self.norm).pack(anchor='w')
        col3 = ttk.Frame(f2)
        col3.grid(row=0, column=2, sticky='nw', padx=20, pady=4)
        ttk.Label(col3, text='Фрагмент (с), порожньо — увесь трек').grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(col3, text='з').grid(row=1, column=0, sticky='e')
        self.start = tk.StringVar(value='0')
        ttk.Entry(col3, textvariable=self.start, width=8).grid(row=1, column=1, sticky='w', pady=2)
        ttk.Label(col3, text='тривалість').grid(row=2, column=0, sticky='e')
        self.length = tk.StringVar(value='')
        ttk.Entry(col3, textvariable=self.length, width=8).grid(row=2, column=1, sticky='w', pady=2)

        f3 = ttk.LabelFrame(root, text=' 3. Дії ')
        f3.pack(fill='x', **pad)
        self.buttons = []
        for text, cmd in (('Згенерувати й перевірити', self.generate),
                          ('Перевірити в CPUlator (автоматично)', self.check_cpulator),
                          ('Відкрити в CPUlator', self.open_cpulator),
                          ('Тека з файлами', self.open_folder),
                          ('Як запустити на платі', self.board_help)):
            b = ttk.Button(f3, text=text, command=cmd)
            b.pack(side='left', padx=6, pady=6)
            self.buttons.append(b)

        self.log_box = ScrolledText(root, height=18, font=('Consolas', 10), state='disabled', wrap='word')
        self.log_box.pack(fill='both', expand=True, **pad)
        self.status = tk.StringVar(value='Оберіть трек (mp3, wav, flac, ogg).')
        ttk.Label(root, textvariable=self.status, anchor='w').pack(fill='x', padx=10, pady=(0, 8))

        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.pump)
        self.log('DE1-SoC Audio Player %s. Файли зберігаються в теці %s'
                 % (__version__, os.path.join(ROOT, 'output')))

    # ------------------------------------------------------------ службове
    def log(self, text):
        self.q.put(('log', text))

    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == 'log':
                    self.log_box.configure(state='normal')
                    self.log_box.insert('end', val + '\n')
                    self.log_box.see('end')
                    self.log_box.configure(state='disabled')
                elif kind == 'status':
                    self.status.set(val)
                elif kind == 'done':
                    self.busy = False
                    for b in self.buttons:
                        b.state(['!disabled'])
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def run_bg(self, title, fn):
        if self.busy:
            return
        self.busy = True
        for b in self.buttons:
            b.state(['disabled'])
        self.q.put(('status', title + '...'))

        def work():
            try:
                fn()
            except Exception as e:
                self.log('ПОМИЛКА: %s' % e)
                self.log(traceback.format_exc(limit=3))
                self.q.put(('status', 'Помилка: %s' % e))
            finally:
                self.q.put(('done', None))
        threading.Thread(target=work, daemon=True).start()

    def need_result(self):
        if not self.result:
            messagebox.showinfo('Спершу файл', 'Спершу натисніть «Згенерувати й перевірити».')
            return False
        return True

    # ------------------------------------------------------------ дії
    def pick(self):
        p = filedialog.askopenfilename(title='Оберіть трек', filetypes=[
            ('Звук', '*.mp3 *.wav *.flac *.ogg'), ('Усі файли', '*.*')])
        if p:
            self.track.set(p)
            self.status.set('Трек обрано. Далі — «Згенерувати й перевірити».')

    def generate(self):
        track = self.track.get()
        if not track:
            messagebox.showinfo('Немає треку', 'Оберіть трек кнопкою «Обрати…».')
            return
        try:
            start = float(self.start.get() or 0)
            length = float(self.length.get()) if self.length.get().strip() else None
        except ValueError:
            messagebox.showerror('Фрагмент', 'Початок і тривалість — числа в секундах.')
            return

        # змінні вікна читаємо тут, у головному потоці: tkinter не любить фонових звертань
        target, codec = self.target.get(), self.codec.get()
        channels, norm = (1 if self.mono.get() else 2), self.norm.get()

        def fn():
            self.log('')
            self.log('=== %s -> %s' % (os.path.basename(track), TARGETS[target].title))
            res = make(track, target, codec, channels, start, length, norm, log=self.log)
            self.result = res
            big = res['nums'].get('needs_bigmem')
            tip = ('для CPUlator відкриється режим із наперед виділеною пам\'яттю' if big
                   else 'вміщується у звичайний CPUlator')
            self.q.put(('status', ('Готово: %s (%s)' % (os.path.basename(res['elf']), tip))
                        if res['ok'] else 'Файл зроблено, але перевірка знайшла помилки — див. журнал'))
        self.run_bg('Генерую', fn)

    def premem(self):
        size = os.path.getsize(self.result['elf']) / 1048576
        return int(min(1024, 64 + 3 * size)) if self.result['nums'].get('needs_bigmem') else 0

    def open_cpulator(self):
        if not self.need_result():
            return
        out = os.path.dirname(self.result['elf'])
        pm = self.premem()
        if self.helper and self.helper.premem_mb != pm:
            self.helper.stop()
            self.helper = None
        if not self.helper:
            self.helper = helper.start(out, pm)
        url = self.helper.url_for(os.path.basename(self.result['elf']))
        self.log('CPUlator: %s%s' % (url, ' (пам\'ять %d МБ)' % pm if pm else ''))
        self.log('Трек завантажиться сам. Натисніть Continue МИШЕЮ — без клацання браузер не вмикає звук.')
        self.log('Якщо за 30 с нічого не сталося — оновіть сторінку кнопкою браузера.')
        if self.result['target'].board:
            self.log('Увага: це файл для плати (%d Гц). CPUlator грає 8 кГц, тож для 48 кГц звук буде '
                     'вшестеро повільнішим — для перевірки кнопок і шкали цього досить.'
                     % self.result['target'].rate)
        webbrowser.open(url)

    def check_cpulator(self):
        if not self.need_result():
            return
        from deplayer import check

        def fn():
            self.log('')
            self.log('=== Автоматична перевірка в CPUlator (браузер без вікна, близько 30 с)')
            ok, lines, nums = check.run(self.result['elf'], self.premem() > 0, log=self.log)
            self.log('Підсумок: %s' % ('усе працює' if ok else 'є зауваження — див. рядки «НІ»'))
            self.q.put(('status', 'Перевірку в CPUlator %s' % ('пройдено' if ok else 'не пройдено')))
        self.run_bg('Перевіряю в CPUlator', fn)

    def open_folder(self):
        d = os.path.dirname(self.result['elf']) if self.result else os.path.join(ROOT, 'output')
        os.makedirs(d, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(d)
        else:
            subprocess.Popen(['xdg-open', d])

    def board_help(self):
        w = tk.Toplevel(self.root)
        w.title('Запуск на платі DE1-SoC')
        w.geometry('720x620')
        t = ScrolledText(w, font=('Consolas', 10), wrap='word')
        t.pack(fill='both', expand=True, padx=8, pady=8)
        t.insert('end', BOARD_STEPS)
        if self.result:
            t.insert('end', '\nЗгенеровані файли:\n' + '\n'.join(self.result['files']) + '\n')
        t.configure(state='disabled')

    def close(self):
        if self.helper:
            self.helper.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
