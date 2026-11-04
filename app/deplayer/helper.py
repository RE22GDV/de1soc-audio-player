# -*- coding: utf-8 -*-
"""Місцевий посередник до CPUlator (cpulator.01xz.net).

Навіщо:
  * автозавантаження — сторінка сама бере згенерований файл із теки output,
    не треба шукати його через File -> Load ELF;
  * наперед виділена пам'ять — у CPUlator є вада: коли він під час роботи
    розширює свою пам'ять WebAssembly, модулі звуку й VGA лишаються
    прив'язаними до старого буфера й замовкають. Для файлів, більших за
    ~2,3 МБ, пам'ять збільшується одразу після старту WebAssembly, ще до
    створення пристроїв (той самий прийом, що в ЛР6).

Усе інше — звичайний CPUlator; потрібен інтернет.
"""
import http.server
import os
import socketserver
import threading
import urllib.error
import urllib.parse
import urllib.request

UP = 'https://cpulator.01xz.net'
SKIP = {'connection', 'keep-alive', 'transfer-encoding', 'content-encoding',
        'content-length', 'upgrade', 'strict-transport-security',
        'content-security-policy', 'cache-control'}
HOOK = (b'wasmMemory=Module["asm"]["memory"];'
        b'assert(wasmMemory,"memory not found in wasm exports");updateMemoryViews();')

AUTOLOAD = r"""
<script>
(async function () {
  var q = new URLSearchParams(location.search), name = q.get('load');
  if (!name) return;
  function banner(t, ok) {
    var b = document.getElementById('de1a_banner');
    if (!b) {
      b = document.createElement('div'); b.id = 'de1a_banner';
      b.style.cssText = 'position:fixed;left:50%;top:6px;transform:translateX(-50%);z-index:99999;' +
        'padding:8px 16px;border-radius:6px;font:14px sans-serif;color:#fff;box-shadow:0 2px 8px #0006;cursor:pointer';
      b.onclick = function () { b.remove(); };
      document.body.appendChild(b);
    }
    b.style.background = ok ? '#1b6e2f' : '#8a1c1c';
    b.textContent = t;
  }
  function started() {
    return (document.body.innerText || '').indexOf('CPUlator has started') >= 0;
  }
  for (var i = 0; i < 300 && !(document.getElementById('fileinput_elf') && started()); i++)
    await new Promise(function (r) { setTimeout(r, 100); });
  function loaded() {
    return (document.body.innerText || '').indexOf('Total size is') >= 0;
  }
  // світлодіоди, кнопки, індикатори й звук — нагору стовпця пристроїв, щоб усе було видно одразу
  var box = document.getElementById('dev_ui_box');
  ['devff203040', 'devff200020', 'devff200050', 'devff200000'].forEach(function (id) {
    var panel = document.getElementById(id);
    if (box && panel) box.prepend(panel);
  });
  try {
    var r = await fetch('/local/' + encodeURIComponent(name), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var buf = await r.arrayBuffer();
    // симулятор інколи ще не готовий прийняти файл — тоді пробуємо ще раз
    for (var attempt = 0; attempt < 4 && !loaded(); attempt++) {
      await new Promise(function (r) { setTimeout(r, attempt ? 3000 : 800); });
      var inp = document.getElementById('fileinput_elf');
      var dt = new DataTransfer(); dt.items.add(new File([buf], name)); inp.files = dt.files;
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      for (var w = 0; w < 100 && !loaded(); w++)
        await new Promise(function (r) { setTimeout(r, 100); });
    }
    if (!loaded()) throw new Error('CPUlator не прийняв файл');
    banner('Трек завантажено (' + (buf.byteLength / 1048576).toFixed(2) +
           ' МБ). Натисніть Continue мишею — KEY0 пауза, KEY1 з початку, KEY2/KEY3 ±10 с', true);
  } catch (e) {
    banner('Не вдалося завантажити ' + name + ': ' + e, false);
  }
})();
</script>
"""


def _patch_cpusim(data, premem_mb):
    if premem_mb <= 0 or data.count(HOOK) != 1:
        return data
    grow = ('(function(){var want=%d*1048576,cur=wasmMemory.buffer.byteLength;'
            'if(cur<want){wasmMemory.grow((want-cur+65535)>>>16);updateMemoryViews();}})();'
            % premem_mb)
    return data.replace(HOOK, HOOK + grow.encode())


def _make_handler(local_dir, premem_mb):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def _send(self, code, data, ctype=None, headers=()):
            self.send_response(code)
            for k, v in headers:
                if k.lower() not in SKIP and not (ctype and k.lower() == 'content-type'):
                    self.send_header(k, v)
            if ctype:
                self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _local(self):
            name = urllib.parse.unquote(self.path[len('/local/'):].split('?')[0])
            name = os.path.basename(name)                       # лише файли з теки output
            p = os.path.join(local_dir, name)
            if not name or not os.path.isfile(p):
                return self._send(404, b'not found', 'text/plain')
            with open(p, 'rb') as f:
                self._send(200, f.read(), 'application/octet-stream')

        def _proxy(self, method):
            body = None
            n = int(self.headers.get('Content-Length') or 0)
            if n:
                body = self.rfile.read(n)
            hdrs = {k: v for k, v in self.headers.items()
                    if k.lower() not in ('host', 'accept-encoding', 'origin', 'referer', 'connection')}
            hdrs['Accept-Encoding'] = 'identity'
            req = urllib.request.Request(UP + self.path, data=body, headers=hdrs, method=method)
            try:
                r = urllib.request.urlopen(req, timeout=60)
                code, rh, data = r.status, r.getheaders(), r.read()
            except urllib.error.HTTPError as e:
                code, rh, data = e.code, list(e.headers.items()), e.read()
            except Exception as e:
                return self._send(502, ('CPUlator недоступний (немає інтернету?): %s' % e).encode('utf-8'),
                                  'text/plain; charset=utf-8')
            path = self.path.split('?')[0]
            if path.startswith('/cpusim.js') and code == 200:
                data = _patch_cpusim(data, premem_mb)
            ctype = dict((k.lower(), v) for k, v in rh).get('content-type', '')
            if code == 200 and 'text/html' in ctype and b'</body>' in data:
                data = data.replace(b'</body>', AUTOLOAD.encode('utf-8') + b'</body>', 1)
            self._send(code, data, None, rh)

        def do_GET(self):
            if self.path.startswith('/local/'):
                return self._local()
            self._proxy('GET')

        def do_POST(self):
            self._proxy('POST')

        def log_message(self, *a):
            pass
    return Handler


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = False        # у Windows інакше порт можуть «ділити» два процеси
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                           # браузер закрив з'єднання — це не помилка


class Helper:
    def __init__(self, server, port, premem_mb):
        self.server, self.port, self.premem_mb = server, port, premem_mb
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    def url_for(self, name=None):
        u = 'http://127.0.0.1:%d/?sys=arm-de1soc' % self.port
        return u + ('&load=' + urllib.parse.quote(name) if name else '')

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def start(local_dir, premem_mb=0, port=8766):
    """Запускає посередник на першому вільному порту, починаючи з port."""
    last = None
    for p in range(port, port + 20):
        try:
            srv = _Server(('127.0.0.1', p), _make_handler(local_dir, premem_mb))
            return Helper(srv, p, premem_mb)
        except OSError as e:
            last = e
    raise RuntimeError('немає вільного порту для CPUlator: %s' % last)
