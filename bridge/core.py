"""
ماژول ارتباط پایتون <-> مرورگر (فقط با کتابخانه‌های داخلی پایتون، بدون نصب چیزی).

  پایتون -> وب :  show(...)  یا  push(...)      (از طریق SSE)
  وب -> پایتون :  py("نام_تابع", ...)            (از طریق fetch / POST)
"""
import base64
import functools
import json
import mimetypes
import os
import sys
import queue
import threading
import traceback
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS  # pyright: ignore[reportAttributeAccessIssue]
else:
    ROOT = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

WEB_DIR = os.path.join(ROOT, "web")

_functions = {}          # توابع پایتونی که JS می‌تواند صدا بزند
_state = {}              # آخرین مقدار هر کلید (برای رفرش صفحه)
_clients = []            # صف پیام هر تب باز مرورگر
_lock = threading.Lock()


# ---------------------------------------------------------------- API برای تو
def expose(func):
    """دکوراتور: تابع را برای JS قابل‌صدازدن می‌کند."""
    _functions[func.__name__] = func
    return func


def push(event, data=None):
    """یک پیام دلخواه به همهٔ صفحه‌ها می‌فرستد (JS با on("event", fn) می‌گیرد)."""
    msg = {"event": event, "data": data}
    with _lock:
        for q in _clients:
            q.put(msg)


def show(**values):
    """
    فقط همین مقدارها را در صفحه عوض می‌کند؛ بقیه دست‌نخورده می‌مانند.
    کلید = مقدار data-bind در HTML.   مثال: show(result=15, logo=image("a.png"))
    """
    with _lock:
        _state.update(values)
    push("show", values)


def image(path):
    """فایل عکس را به رشته‌ای تبدیل می‌کند که مستقیم در show() قابل‌استفاده است."""
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def save_image(data_url, path):
    """عکسی که از وب آمده (data URL) را روی دیسک ذخیره می‌کند."""
    raw = data_url.split(",", 1)[1]
    with open(path, "wb") as f:
        f.write(base64.b64decode(raw))


# ----------------------------------------------------------------- سرور داخلی
class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")   # با رفرش، تغییرات فایل‌ها دیده شود
        super().end_headers()

    def do_GET(self):
        if self.path == "/_events":
            return self._events()
        super().do_GET()

    def do_POST(self):
        if self.path != "/_call":
            return self.send_error(404)
        try:
            size = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(size).decode("utf-8"))
            result = _functions[req["name"]](*req.get("args", []))
            out = {"ok": True, "result": result}
        except Exception as e:
            traceback.print_exc()
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        body = json.dumps(out, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        q = queue.Queue()
        with _lock:
            if _state:
                q.put({"event": "show", "data": dict(_state)})   # وضعیت فعلی برای تب جدید
            _clients.append(q)
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    line = "data: " + json.dumps(msg, ensure_ascii=False, default=str) + "\n\n"
                except queue.Empty:
                    line = ": ping\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with _lock:
                _clients.remove(q)


def run(port=8765, open_browser=True):
    handler = functools.partial(_Handler, directory=WEB_DIR)
    server = None
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), handler)
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError("there is no open ports")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Running on: {url}   (Exit -> Ctrl+C)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n Exit.")
