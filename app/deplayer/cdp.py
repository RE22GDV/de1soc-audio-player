# -*- coding: utf-8 -*-
"""Мінімальне керування Chrome/Edge без вікна через DevTools Protocol."""
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

try:
    import websocket
except ImportError:                                  # pragma: no cover
    websocket = None

CANDIDATES = [
    r'%ProgramFiles%\Google\Chrome\Application\chrome.exe',
    r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe',
    r'%LocalAppData%\Google\Chrome\Application\chrome.exe',
    r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe',
    r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe',
]


def find_browser():
    for c in CANDIDATES:
        p = os.path.expandvars(c)
        if os.path.isfile(p):
            return p
    for name in ('chrome', 'msedge', 'chromium'):
        p = shutil.which(name)
        if p:
            return p
    return None


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Browser:
    def __init__(self, url, width=1600, height=1000, scale=1):
        if websocket is None:
            raise RuntimeError('немає бібліотеки websocket-client (її ставить run.bat)')
        exe = find_browser()
        if not exe:
            raise RuntimeError('не знайдено Chrome або Edge')
        self.port = _free_port()
        self.prof = tempfile.mkdtemp(prefix='de1a_chrome_')
        self.proc = subprocess.Popen(
            [exe, '--headless=new', '--remote-debugging-port=%d' % self.port,
             '--user-data-dir=' + self.prof, '--no-first-run', '--no-default-browser-check',
             '--autoplay-policy=no-user-gesture-required',
             '--window-size=%d,%d' % (width, height), 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(60):
            try:
                tabs = json.loads(urllib.request.urlopen('http://127.0.0.1:%d/json' % self.port,
                                                         timeout=1).read())
                pages = [t for t in tabs if t.get('type') == 'page']
                if pages:
                    ws_url = pages[0]['webSocketDebuggerUrl']
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws_url:
            self.close()
            raise RuntimeError('браузер не відповів')
        self.ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
        self.n = 0
        self.call('Page.enable')
        self.call('Runtime.enable')
        self.call('Emulation.setDeviceMetricsOverride', width=width, height=height,
                  deviceScaleFactor=scale, mobile=False)
        self.call('Page.navigate', url=url)

    def call(self, method, **params):
        self.n += 1
        my = self.n
        self.ws.send(json.dumps({'id': my, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == my:
                if 'error' in msg:
                    raise RuntimeError('%s: %s' % (method, msg['error']))
                return msg.get('result', {})

    def js(self, expr, timeout=60):
        r = self.call('Runtime.evaluate', expression='(async()=>{%s})()' % expr,
                      awaitPromise=True, returnByValue=True, timeout=timeout * 1000)
        if 'exceptionDetails' in r:
            raise RuntimeError(json.dumps(r['exceptionDetails'])[:400])
        return r.get('result', {}).get('value')

    def click(self, x, y):
        for t in ('mousePressed', 'mouseReleased'):
            self.call('Input.dispatchMouseEvent', type=t, x=x, y=y, button='left', clickCount=1)

    def rect(self, selector_js):
        return self.js('const e=%s; if(!e) return null; const r=e.getBoundingClientRect(); '
                       'return {x:r.x+scrollX, y:r.y+scrollY, w:r.width, h:r.height};' % selector_js)

    def shot(self, path):
        data = self.call('Page.captureScreenshot', format='png', captureBeyondViewport=True)['data']
        with open(path, 'wb') as f:
            f.write(base64.b64decode(data))
        return path

    def close(self):
        try:
            self.call('Browser.close')
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.prof, ignore_errors=True)
