"""
MicBridge audio engine.

Architecture
  * Each mic = its own InputStream (any device, any host API: WASAPI, ASIO, MME...).
    The input callback runs the DSP chain and pushes stereo audio into a tiny ring buffer.
  * One OutputStream on the chosen output device pulls from every mic's ring,
    mixes, routes to Front L/R and/or Center, soft-limits and plays.
  * Ring buffers are kept ~1 block deep (drift control drops excess), so the added
    software latency is roughly: input buffer + 1 block + output buffer (~8-15 ms with
    WASAPI exclusive / ASIO at 128 frames).
  * ASIO note: PortAudio can only open an ASIO driver once, so when the OUTPUT is an
    ASIO device every mic must be an input channel of that same ASIO device, and the
    engine switches to a single full-duplex stream.
"""
import os
import time
import math
import json
import threading
from pathlib import Path

os.environ.setdefault("SD_ENABLE_ASIO", "1")  # sounddevice >= 0.5 ships an ASIO-enabled PortAudio
import numpy as np
import sounddevice as sd

from .dsp import VoiceChain, PRESETS, EQ_BANDS

SETTINGS_FILE = Path(os.environ.get("MICBRIDGE_SETTINGS", Path.home() / ".micbridge" / "settings.json"))

DEFAULT_SETTINGS = {
    "samplerate": 48000,
    "blocksize": 128,
    "output": {"device": None, "volume_db": 0.0, "routing": "front", "exclusive": False},
    "input_exclusive": True,
    "show_all_apis": False,
    "mics": [],
}

DEFAULT_MIC = {
    "id": None, "name": "", "device": None, "channel": 0, "enabled": True, "muted": False,
    "gain_db": 0.0, "auto_gain": False, "gate": True, "gate_db": -55.0, "pan": 0.0,
    "preset": "Karaoke Classic", "fx": None,
}


# --------------------------------------------------------------------------
# Device helpers — devices are persisted as "Name || HostAPI" because indexes change
# --------------------------------------------------------------------------

def rescan():
    """Re-enumerate devices so hot-plugged USB receivers show up."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def list_devices():
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        api = apis[d["hostapi"]]["name"]
        out.append({
            "index": i, "name": d["name"], "hostapi": api, "key": f"{d['name']} || {api}",
            "inputs": d["max_input_channels"], "outputs": d["max_output_channels"],
            "samplerate": d["default_samplerate"],
            "low_in_ms": round(d["default_low_input_latency"] * 1000, 1),
            "low_out_ms": round(d["default_low_output_latency"] * 1000, 1),
            "is_default_in": i == _default(0), "is_default_out": i == _default(1),
        })
    return out


def _default(kind):
    try:
        v = sd.default.device[kind]
        return v if v is not None and v >= 0 else sd.query_hostapis(_wasapi_index() or 0)["default_input_device" if kind == 0 else "default_output_device"]
    except Exception:
        return -1


def _wasapi_index():
    for i, a in enumerate(sd.query_hostapis()):
        if "WASAPI" in a["name"]:
            return i
    return None


def resolve(key, want_in):
    """Map a saved key back to a device index; fall back to name match, then default."""
    devs = list_devices()
    ok = [d for d in devs if (d["inputs"] if want_in else d["outputs"]) > 0]
    if key:
        for d in ok:
            if d["key"] == key:
                return d
        name = key.split(" || ")[0]
        for d in ok:
            if d["name"] == name:
                return d
    # default: prefer WASAPI default device
    wi = _wasapi_index()
    if wi is not None:
        idx = sd.query_hostapis(wi)["default_input_device" if want_in else "default_output_device"]
        for d in ok:
            if d["index"] == idx:
                return d
    return ok[0] if ok else None


def _extra(dev, exclusive):
    if "WASAPI" not in dev["hostapi"]:
        return None
    try:
        return sd.WasapiSettings(exclusive=exclusive, auto_convert=not exclusive)
    except TypeError:
        return sd.WasapiSettings(exclusive=exclusive)


# --------------------------------------------------------------------------

class Ring:
    def __init__(self, cap):
        self.buf = np.zeros((cap, 2), dtype=np.float32)
        self.cap = cap
        self.r = self.w = self.n = 0
        self.lock = threading.Lock()
        self.underruns = 0
        self.dropped = 0

    def write(self, data):
        with self.lock:
            m = len(data)
            if m > self.cap:
                data, m = data[-self.cap:], self.cap
            idx = (self.w + np.arange(m)) % self.cap
            self.buf[idx] = data
            self.w = (self.w + m) % self.cap
            self.n = min(self.cap, self.n + m)
            if self.n == self.cap:
                self.r = self.w

    def read(self, m, target):
        with self.lock:
            # drift control: never let the queue grow past target + 2 blocks
            excess = self.n - (target + 2 * m)
            if excess > 0:
                self.r = (self.r + excess) % self.cap
                self.n -= excess
                self.dropped += excess
            take = min(m, self.n)
            out = np.zeros((m, 2), dtype=np.float32)
            if take:
                idx = (self.r + np.arange(take)) % self.cap
                out[:take] = self.buf[idx]
                self.r = (self.r + take) % self.cap
                self.n -= take
            if take < m:
                self.underruns += 1
            return out, self.n


class Meter:
    def __init__(self):
        self.peak = 0.0
        self.rms = 0.0

    def update(self, x):
        if len(x):
            p = float(np.max(np.abs(x)))
            self.peak = max(p, self.peak * 0.85)
            self.rms = 0.8 * self.rms + 0.2 * math.sqrt(float(np.mean(x * x)))

    def db(self):
        return {"peak": round(20 * math.log10(max(self.peak, 1e-6)), 1),
                "rms": round(20 * math.log10(max(self.rms, 1e-6)), 1)}


class Mic:
    def __init__(self, cfg, fs):
        self.cfg = cfg
        self.chain = VoiceChain(fs)
        self.apply_fx()
        self.ring = Ring(fs)  # 1 s capacity
        self.meter = Meter()
        self.stream = None
        self.dev = None
        self.error = None
        self.in_latency = 0.0
        self.record = None  # list of blocks while "Test microphone" is recording
        self.click_listen = None

    def fx(self):
        base = dict(PRESETS.get(self.cfg.get("preset"), PRESETS["Natural"]))
        if self.cfg.get("fx"):  # user tweaks on top of preset
            o = self.cfg["fx"]
            base.update({k: v for k, v in o.items() if k != "eq"})
            if "eq" in o:
                base["eq"] = {**base["eq"], **o["eq"]}
        return base

    def apply_fx(self):
        self.chain.configure(self.fx())

    def process(self, mono):
        c = self.cfg
        l, r, level = self.chain.process(mono, c["gain_db"], c["auto_gain"], c["gate"], c["gate_db"], c["pan"])
        self.meter.update(level)
        if c["muted"]:
            l = l * 0
            r = r * 0
        return np.stack([l, r], axis=1).astype(np.float32), level


class Engine:
    def __init__(self):
        self.settings = self.load()
        self.lock = threading.RLock()
        self.mics = {}
        self.out_stream = None
        self.duplex = None
        self.out_dev = None
        self.out_meter = Meter()
        self.out_latency = 0.0
        self.running = False
        self.status = "stopped"
        self.errors = []
        self.cb_load = 0.0
        self._test_tone = None   # (array, pos) for speaker test / playback / click
        self._click = None       # dict while latency test runs
        self.last_latency_test = None
        self.last_record = None

    # ---------------- settings ----------------
    def load(self):
        try:
            s = json.loads(SETTINGS_FILE.read_text())
            merged = json.loads(json.dumps(DEFAULT_SETTINGS))
            merged.update(s)
            merged["output"] = {**DEFAULT_SETTINGS["output"], **s.get("output", {})}
            merged["mics"] = [{**DEFAULT_MIC, **m} for m in s.get("mics", [])]
            return merged
        except Exception:
            return json.loads(json.dumps(DEFAULT_SETTINGS))

    def save(self):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))

    @property
    def fs(self):
        return int(self.settings["samplerate"])

    @property
    def bs(self):
        return int(self.settings["blocksize"])

    # ---------------- lifecycle ----------------
    def start(self):
        with self.lock:
            self.stop()
            self.errors = []
            rescan()
            if not self.settings["mics"]:
                d = resolve(None, True)
                if d:
                    self.add_mic(d["key"], save=False)
            self.out_dev = resolve(self.settings["output"]["device"], False)
            if not self.out_dev:
                self.errors.append("No output device found")
                self.status = "error"
                return
            self.mics = {m["id"]: Mic(m, self.fs) for m in self.settings["mics"] if m["enabled"]}
            if "ASIO" in self.out_dev["hostapi"]:
                self._start_duplex()
            else:
                self._start_split()
            self.running = True
            self.status = "running" if not self.errors else "running (with errors)"

    def stop(self):
        with self.lock:
            for s in [self.out_stream, self.duplex] + [m.stream for m in self.mics.values()]:
                if s is not None:
                    try:
                        s.stop(); s.close()
                    except Exception:
                        pass
            self.out_stream = self.duplex = None
            for m in self.mics.values():
                m.stream = None
            self.running = False
            self.status = "stopped"

    def _start_split(self):
        o = self.settings["output"]
        nch = max(2, min(self.out_dev["outputs"], 8))
        if o["routing"] == "front":
            nch = 2
        try:
            self.out_stream = sd.OutputStream(
                device=self.out_dev["index"], channels=nch, samplerate=self.fs, blocksize=self.bs,
                dtype="float32", latency="low", callback=self._out_cb,
                extra_settings=_extra(self.out_dev, o["exclusive"]))
            self.out_stream.start()
            self.out_latency = self.out_stream.latency
        except Exception as e:
            self.errors.append(f"Output '{self.out_dev['name']}': {e}")
            return
        for mic in self.mics.values():
            self._open_mic(mic)

    def _open_mic(self, mic):
        d = resolve(mic.cfg["device"], True)
        if not d:
            mic.error = "device not found (unplugged?)"
            self.errors.append(f"Mic {mic.cfg['id']}: {mic.error}")
            return
        mic.dev = d
        ch = int(mic.cfg["channel"])
        nin = min(d["inputs"], max(ch + 1, 1))

        def cb(indata, frames, t, status, mic=mic, ch=ch):
            t0 = time.perf_counter()
            mono = indata[:, ch] if ch >= 0 and ch < indata.shape[1] else indata.mean(axis=1)
            stereo, level = mic.process(mono)
            mic.ring.write(stereo)
            if mic.record is not None:
                mic.record.append(stereo.copy())
            self._listen_click(level, t0, mic)
            self.cb_load = max(self.cb_load * 0.95, (time.perf_counter() - t0) / (frames / self.fs))

        excl = self.settings["input_exclusive"]
        for attempt in ((excl,) if not excl else (True, False)):
            try:
                mic.stream = sd.InputStream(device=d["index"], channels=nin, samplerate=self.fs,
                                            blocksize=self.bs, dtype="float32", latency="low",
                                            callback=cb, extra_settings=_extra(d, attempt))
                mic.stream.start()
                mic.in_latency = mic.stream.latency
                mic.exclusive = attempt and "WASAPI" in d["hostapi"]
                mic.error = None
                return
            except Exception as e:
                mic.error = str(e)
        self.errors.append(f"Mic '{d['name']}': {mic.error}")

    def _start_duplex(self):
        """ASIO path: one full-duplex stream, mics = channels of the ASIO device."""
        d = self.out_dev
        chans = [int(m.cfg["channel"]) for m in self.mics.values()] or [0]
        nin = min(d["inputs"], max(chans) + 1)
        nout = 2 if self.settings["output"]["routing"] == "front" else max(2, min(d["outputs"], 8))
        for m in self.mics.values():
            m.dev = d

        def cb(indata, outdata, frames, t, status):
            t0 = time.perf_counter()
            mix = np.zeros((frames, 2), dtype=np.float32)
            for m in list(self.mics.values()):
                ch = int(m.cfg["channel"])
                if ch >= indata.shape[1]:
                    continue
                st, level = m.process(indata[:, ch])
                mix += st
                if m.record is not None:
                    m.record.append(st.copy())
                self._listen_click(level, t0, m)
            self._finish(mix, outdata, t0)
            self.cb_load = max(self.cb_load * 0.95, (time.perf_counter() - t0) / (frames / self.fs))

        try:
            self.duplex = sd.Stream(device=(d["index"], d["index"]), channels=(nin, nout),
                                    samplerate=self.fs, blocksize=self.bs, dtype="float32",
                                    latency="low", callback=cb)
            self.duplex.start()
            self.out_latency = self.duplex.latency[1]
            for m in self.mics.values():
                m.in_latency = self.duplex.latency[0]
        except Exception as e:
            self.errors.append(f"ASIO '{d['name']}': {e}")

    # ---------------- callbacks ----------------
    def _out_cb(self, outdata, frames, t, status):
        t0 = time.perf_counter()
        mix = np.zeros((frames, 2), dtype=np.float32)
        for m in list(self.mics.values()):
            if m.stream is None:
                continue
            data, _ = m.ring.read(frames, target=frames)
            mix += data
        self._finish(mix, outdata, t0)

    def _finish(self, mix, outdata, t0):
        frames = len(mix)
        # test tones / mic playback / latency click
        tt = self._test_tone
        if tt is not None:
            arr, pos = tt
            seg = arr[pos:pos + frames]
            mix[:len(seg)] += seg
            if tt is self._test_tone:
                self._test_tone = (arr, pos + frames) if pos + frames < len(arr) else None
            if self._click is not None and self._click.get("emit") is None and pos == 0:
                self._click["emit"] = t0 + self.out_latency
        vol = 10 ** (self.settings["output"]["volume_db"] / 20)
        mix *= vol
        # soft limiter above -1 dBFS
        np.clip(mix, -1.5, 1.5, out=mix)
        over = np.abs(mix) > 0.89
        if over.any():
            mix[over] = np.sign(mix[over]) * (0.89 + 0.11 * np.tanh((np.abs(mix[over]) - 0.89) / 0.11))
        self.out_meter.update(mix[:, 0])
        outdata.fill(0)
        routing = self.settings["output"]["routing"]
        nch = outdata.shape[1]
        if routing in ("front", "front+center") or nch < 3:
            outdata[:, 0] = mix[:, 0]
            outdata[:, 1] = mix[:, 1]
        if routing in ("center", "front+center") and nch >= 3:
            outdata[:, 2] = (mix[:, 0] + mix[:, 1]) * 0.5
        if routing == "all" and nch >= 2:
            for c in range(nch):
                if c != 3:  # skip LFE
                    outdata[:, c] = mix[:, c % 2]

    def _listen_click(self, level, t_cb, mic):
        c = self._click
        if c is None or c.get("emit") is None or c.get("hit") is not None:
            return
        if t_cb < c["emit"] - 0.05:
            return
        idx = np.flatnonzero(np.abs(level) > c["threshold"])
        if len(idx):
            adc_time = t_cb - mic.in_latency - (len(level) - idx[0]) / self.fs
            c["hit"] = adc_time
            c["mic"] = mic.cfg["id"]

    # ---------------- tests ----------------
    def test_speaker(self):
        fs = self.fs
        t = np.arange(int(fs * 1.2)) / fs
        tone = 0.25 * np.sin(2 * np.pi * 523.25 * t) * np.minimum(1, np.minimum(t * 40, (t[-1] - t) * 10))
        tone2 = 0.25 * np.sin(2 * np.pi * 659.25 * t) * np.minimum(1, np.minimum(t * 40, (t[-1] - t) * 10))
        self._test_tone = (np.stack([tone, tone2], 1).astype(np.float32), 0)

    def record_test(self, seconds=4.0):
        """Zoom-style: record processed mic for N s, then play it back."""
        mics = list(self.mics.values())
        if not mics:
            return {"ok": False, "error": "no running mic"}
        for m in mics:
            m.record = []
        time.sleep(seconds)
        blocks = []
        for m in mics:
            blocks.append(np.concatenate(m.record) if m.record else np.zeros((0, 2), np.float32))
            m.record = None
        n = max(len(b) for b in blocks)
        rec = np.zeros((n, 2), np.float32)
        for b in blocks:
            rec[:len(b)] += b
        # mute live mics while playing back so you only hear the recording
        saved = [m.cfg["muted"] for m in mics]
        for m in mics:
            m.cfg["muted"] = True
        self._test_tone = (rec, 0)
        time.sleep(n / self.fs + 0.2)
        for m, s in zip(mics, saved):
            m.cfg["muted"] = s
        peak = float(np.max(np.abs(rec))) if n else 0
        self.last_record = {"seconds": round(n / self.fs, 2),
                            "peak_db": round(20 * math.log10(max(peak, 1e-6)), 1)}
        return {"ok": True, **self.last_record}

    def latency_test(self):
        """Play a click through the speakers and time when a mic hears it.
        Measures the WHOLE chain: software + sound card + optical/DDL + AV receiver + air."""
        if not self.running or not self.mics:
            return {"ok": False, "error": "start the engine with at least one mic first"}
        results = []
        fs = self.fs
        for trial in range(3):
            n = int(fs * 0.004)
            click = np.zeros((int(fs * 0.6), 2), np.float32)
            burst = (np.random.RandomState(trial).uniform(-1, 1, n) * np.hanning(n) * 0.9).astype(np.float32)
            click[:n, 0] = burst
            click[:n, 1] = burst
            mics = list(self.mics.values())
            saved = [m.cfg["muted"] for m in mics]
            for m in mics:
                m.cfg["muted"] = True  # avoid feedback loop during test
            noise = max(10 ** (m.meter.db()["peak"] / 20) for m in mics)
            self._click = {"emit": None, "hit": None, "threshold": max(0.08, noise * 4)}
            self._test_tone = (click, 0)
            t_end = time.perf_counter() + 1.5
            while time.perf_counter() < t_end and self._click.get("hit") is None:
                time.sleep(0.005)
            c = self._click
            self._click = None
            for m, s in zip(mics, saved):
                m.cfg["muted"] = s
            if c.get("hit") and c.get("emit"):
                results.append(float((c["hit"] - c["emit"]) * 1000))
            time.sleep(0.25)
        sw = self.software_latency_ms()
        if not results:
            out = {"ok": False, "software_ms": sw,
                   "error": "Mic never heard the click. Hold the mic ~30 cm from a front speaker, turn the volume up and retry."}
        else:
            acoustic = float(np.median(results))
            out = {"ok": True, "software_ms": sw, "trials_ms": [round(r, 1) for r in results],
                   "speaker_to_mic_ms": round(acoustic, 1),
                   # what a singer perceives = mic->speaker; approx equal to speaker->mic loop here
                   "round_trip_ms": round(acoustic + sw["input_ms"], 1)}
        self.last_latency_test = out
        return out

    def software_latency_ms(self):
        ins = [m.in_latency for m in self.mics.values() if m.stream is not None or self.duplex] or [0]
        ring = 0 if self.duplex else self.bs / self.fs
        return {"input_ms": round(max(ins) * 1000, 1), "buffer_ms": round(ring * 1000, 1),
                "output_ms": round(self.out_latency * 1000, 1),
                "total_ms": round((max(ins) + ring + self.out_latency) * 1000, 1)}

    # ---------------- mic config ----------------
    def add_mic(self, device_key=None, save=True):
        ids = {m["id"] for m in self.settings["mics"]}
        n = 1
        while f"mic{n}" in ids:
            n += 1
        m = {**DEFAULT_MIC, "id": f"mic{n}", "device": device_key}
        self.settings["mics"].append(m)
        if save:
            self.save()
        return m

    def remove_mic(self, mid):
        self.settings["mics"] = [m for m in self.settings["mics"] if m["id"] != mid]
        self.save()

    def update_mic(self, mid, patch):
        """Live-tweakable fields apply instantly; device/channel changes need a restart."""
        restart = False
        for m in self.settings["mics"]:
            if m["id"] != mid:
                continue
            for k, v in patch.items():
                if k in ("device", "channel", "enabled") and m.get(k) != v:
                    restart = True
                if k == "preset":
                    m["fx"] = None
                if k == "fx":
                    cur = m.get("fx") or {}
                    if "eq" in v:
                        cur["eq"] = {**cur.get("eq", {}), **v["eq"]}
                    cur.update({kk: vv for kk, vv in v.items() if kk != "eq"})
                    v = cur
                m[k] = v
            live = self.mics.get(mid)
            if live:
                live.cfg = m
                live.apply_fx()
        self.save()
        return restart

    def update(self, patch):
        restart = False
        for k, v in patch.items():
            if k == "output":
                for kk, vv in v.items():
                    if kk in ("device", "routing", "exclusive") and self.settings["output"].get(kk) != vv:
                        restart = True
                    self.settings["output"][kk] = vv
            else:
                if k in ("samplerate", "blocksize", "input_exclusive") and self.settings.get(k) != v:
                    restart = True
                self.settings[k] = v
        self.save()
        return restart

    def state(self):
        mics = []
        for m in self.settings["mics"]:
            live = self.mics.get(m["id"])
            mics.append({**m, "fx_resolved": (live.fx() if live else Mic(m, self.fs).fx()),
                         "running": bool(live and (live.stream is not None or self.duplex)),
                         "error": live.error if live else None,
                         "exclusive": getattr(live, "exclusive", False) if live else False,
                         "resolved_device": live.dev["key"] if live and live.dev else None})
        return {"settings": self.settings, "mics": mics, "running": self.running, "status": self.status,
                "errors": self.errors, "output_device": self.out_dev["key"] if self.out_dev else None,
                "latency": self.software_latency_ms() if self.running else None,
                "last_latency_test": self.last_latency_test, "last_record": self.last_record,
                "presets": list(PRESETS), "eq_bands": [[k, f] for k, f, *_ in EQ_BANDS],
                "mode": "asio-duplex" if self.duplex else "split"}

    def meters(self):
        return {"out": self.out_meter.db(), "cpu": round(self.cb_load * 100),
                "mics": {mid: {**m.meter.db(), "underruns": m.ring.underruns,
                               "gr": round(m.chain.comp.gr_db, 1), "agc": round(m.chain.agc.gain_db, 1),
                               "gate": round(m.chain.gate.gain, 2)}
                         for mid, m in self.mics.items()}}
