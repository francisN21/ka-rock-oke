"""MicBridge settings server.  python -m micbridge  ->  http://localhost:5556"""
import argparse
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import engine as eng

STATIC = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=str(STATIC))
E: eng.Engine = None
busy = threading.Lock()


def ok(**kw):
    return jsonify({"ok": True, **kw})


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/devices")
def devices():
    if request.args.get("rescan") and not E.running:
        eng.rescan()
    return jsonify(eng.list_devices())


@app.get("/api/state")
def state():
    return jsonify(E.state())


@app.get("/api/meters")
def meters():
    return jsonify(E.meters())


@app.post("/api/start")
def start():
    E.start()
    return jsonify(E.state())


@app.post("/api/stop")
def stop():
    E.stop()
    return jsonify(E.state())


@app.post("/api/settings")
def settings():
    restart = E.update(request.json or {})
    if restart and E.running:
        E.start()
    return jsonify(E.state())


@app.post("/api/mics")
def add_mic():
    E.add_mic((request.json or {}).get("device"))
    if E.running:
        E.start()
    return jsonify(E.state())


@app.post("/api/mics/<mid>")
def patch_mic(mid):
    restart = E.update_mic(mid, request.json or {})
    if restart and E.running:
        E.start()
    return jsonify(E.state())


@app.delete("/api/mics/<mid>")
def del_mic(mid):
    E.remove_mic(mid)
    if E.running:
        E.start()
    return jsonify(E.state())


@app.post("/api/test/speaker")
def t_speaker():
    if not E.running:
        E.start()
    E.test_speaker()
    return ok()


@app.post("/api/test/record")
def t_record():
    if not busy.acquire(blocking=False):
        return jsonify({"ok": False, "error": "another test is running"})
    try:
        if not E.running:
            E.start()
        return jsonify(E.record_test(float((request.json or {}).get("seconds", 4))))
    finally:
        busy.release()


@app.post("/api/test/latency")
def t_latency():
    if not busy.acquire(blocking=False):
        return jsonify({"ok": False, "error": "another test is running"})
    try:
        if not E.running:
            E.start()
        return jsonify(E.latency_test())
    finally:
        busy.release()


def main():
    global E
    ap = argparse.ArgumentParser(description="MicBridge - low-latency karaoke mic monitor")
    ap.add_argument("--port", type=int, default=5556)
    ap.add_argument("--lan", action="store_true", help="allow other devices on the network to open the settings page")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-autostart", action="store_true", help="don't start the mics on launch")
    a = ap.parse_args()
    E = eng.Engine()
    if not a.no_autostart:
        try:
            E.start()
        except Exception as e:  # keep UI up so the user can pick devices
            E.errors.append(str(e))
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{a.port}")).start()
    print(f"MicBridge settings: http://localhost:{a.port}")
    app.run(host=host, port=a.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
