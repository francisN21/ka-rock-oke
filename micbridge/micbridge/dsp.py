"""
MicBridge DSP - block-based, numpy/scipy only, no per-sample Python loops.

Chain per mic:  gain -> auto-gain -> noise gate -> low-cut + 6-band EQ
                -> compressor -> echo + reverb -> pan to stereo
"""
import math
import numpy as np
from scipy.signal import sosfilt, lfilter

# --------------------------------------------------------------------------
# Biquads (RBJ audio EQ cookbook)
# --------------------------------------------------------------------------

def biquad_sos(kind, f0, fs, q=0.707, gain_db=0.0):
    f0 = max(10.0, min(f0, fs * 0.45))
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "lowshelf":
        sa = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa)]
        a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    elif kind == "highshelf":
        sa = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa)]
        a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(kind)
    a0 = a[0]
    return np.array([[b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0]])


EQ_BANDS = [  # (key, freq, kind, q)
    ("b100", 100, "lowshelf", 0.707),
    ("b250", 250, "peak", 1.0),
    ("b800", 800, "peak", 1.0),
    ("b2k5", 2500, "peak", 1.0),
    ("b5k", 5000, "peak", 1.0),
    ("b10k", 10000, "highshelf", 0.707),
]


class Equalizer:
    def __init__(self, fs):
        self.fs = fs
        self.sos = None
        self.zi = None
        self.sig = None

    def configure(self, lowcut_hz, gains):
        sig = (round(lowcut_hz), tuple(round(gains.get(k, 0.0), 2) for k, *_ in EQ_BANDS))
        if sig == self.sig:
            return
        self.sig = sig
        rows = []
        if lowcut_hz and lowcut_hz > 20:
            rows.append(biquad_sos("highpass", lowcut_hz, self.fs, 0.707))
        for key, f, kind, q in EQ_BANDS:
            g = float(gains.get(key, 0.0))
            if abs(g) > 0.05:
                rows.append(biquad_sos(kind, f, self.fs, q, g))
        if rows:
            new = np.vstack(rows)
            # keep state if section count unchanged to avoid clicks
            if self.sos is None or self.sos.shape != new.shape:
                self.zi = np.zeros((new.shape[0], 2))
            self.sos = new
        else:
            self.sos, self.zi = None, None

    def process(self, x):
        if self.sos is None:
            return x
        y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        return y


# --------------------------------------------------------------------------
# Feedback delay line, vectorised in chunks no longer than the delay
# --------------------------------------------------------------------------

class FeedbackDelay:
    """v[n] = x[n] + g * damp(v[n-D]);  returns (delayed_raw, delayed_damped)."""

    def __init__(self, delay, feedback=0.5, damp=0.0, max_block=4096):
        self.size = delay + max_block + 8
        self.buf = np.zeros(self.size)
        self.w = 0
        self.set(delay, feedback, damp)

    def set(self, delay, feedback, damp):
        delay = int(max(1, delay))
        if delay + 8 > self.size:
            self.size = delay + 4096 + 8
            self.buf = np.zeros(self.size)
            self.w = 0
        self.D = delay
        self.g = float(feedback)
        d = float(min(max(damp, 0.0), 0.99))
        if d > 0:
            self.b, self.a = np.array([1 - d]), np.array([1.0, -d])
            if not hasattr(self, "zi") or self.zi is None:
                self.zi = np.zeros(1)
        else:
            self.b = self.a = None
            self.zi = None

    def process(self, x):
        n = len(x)
        raw = np.empty(n)
        damped = np.empty(n)
        i = 0
        while i < n:
            m = min(self.D, n - i)
            ridx = (self.w - self.D + np.arange(m)) % self.size
            d = self.buf[ridx]
            if self.b is not None:
                df, self.zi = lfilter(self.b, self.a, d, zi=self.zi)
            else:
                df = d
            v = x[i:i + m] + self.g * df
            widx = (self.w + np.arange(m)) % self.size
            self.buf[widx] = v
            self.w = (self.w + m) % self.size
            raw[i:i + m] = d
            damped[i:i + m] = df
            i += m
        return raw, damped

    def clear(self):
        self.buf[:] = 0
        if self.zi is not None:
            self.zi[:] = 0


class Echo:
    """Classic karaoke echo: feedback delay with darkening repeats."""

    def __init__(self, fs):
        self.fs = fs
        self.line = FeedbackDelay(int(0.2 * fs), 0.35, 0.3)
        self.tone = None

    def configure(self, time_ms, feedback, damp):
        self.line.set(int(fs_ms(self.fs, time_ms)), min(feedback, 0.9), damp)

    def process(self, x):
        _, wet = self.line.process(x)
        return wet


def fs_ms(fs, ms):
    return fs * ms / 1000.0


class Reverb:
    """Freeverb-style: 8 parallel damped combs + 4 series allpasses, stereo spread."""

    COMBS = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
    ALLPASS = [556, 441, 341, 225]
    SPREAD = 23

    def __init__(self, fs):
        self.fs = fs
        s = fs / 44100.0
        self.combs = [[FeedbackDelay(int((c + o) * s), 0.84, 0.2) for c in self.COMBS] for o in (0, self.SPREAD)]
        self.aps = [[FeedbackDelay(int((a + o) * s), 0.5, 0.0) for a in self.ALLPASS] for o in (0, self.SPREAD)]
        self.sig = None

    def configure(self, room, damp):
        sig = (round(room, 3), round(damp, 3))
        if sig == self.sig:
            return
        self.sig = sig
        fb = 0.70 + 0.28 * min(max(room, 0.0), 1.0)
        for side in self.combs:
            for c in side:
                c.set(c.D, fb, damp * 0.4)

    def process(self, x):
        x = x * 0.015  # freeverb fixed gain
        out = []
        for side in range(2):
            acc = np.zeros(len(x))
            for c in self.combs[side]:
                raw, _ = c.process(x)
                acc += raw
            for ap in self.aps[side]:
                raw, _ = ap.process(acc)
                acc = raw - acc
            out.append(acc)
        return out[0], out[1]


# --------------------------------------------------------------------------
# Dynamics
# --------------------------------------------------------------------------

def _db(x):
    return 20 * math.log10(max(x, 1e-9))


class Gate:
    def __init__(self):
        self.gain = 1.0

    def process(self, x, threshold_db, enabled):
        if not enabled:
            self.gain = 1.0
            return x
        rms = math.sqrt(float(np.mean(x * x)) + 1e-12)
        target = 1.0 if _db(rms) > threshold_db else 0.0
        coef = 0.5 if target > self.gain else 0.08   # fast open, slow close
        new = self.gain + (target - self.gain) * coef
        ramp = np.linspace(self.gain, new, len(x), endpoint=False)
        self.gain = new
        return x * ramp


class Compressor:
    def __init__(self):
        self.gr_db = 0.0

    def process(self, x, threshold_db, ratio, enabled):
        if not enabled or ratio <= 1.0:
            self.gr_db = 0.0
            return x
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        lvl = _db(peak)
        over = lvl - threshold_db
        target = -(over - over / ratio) if over > 0 else 0.0
        coef = 0.6 if target < self.gr_db else 0.03
        prev = self.gr_db
        self.gr_db += (target - self.gr_db) * coef
        ramp = np.linspace(10 ** (prev / 20), 10 ** (self.gr_db / 20), len(x), endpoint=False)
        return x * ramp


class AutoGain:
    """Slow AGC toward a target vocal level, only adapts while someone is singing."""

    def __init__(self):
        self.gain_db = 0.0

    def process(self, x, enabled, target_db=-20.0):
        if not enabled:
            self.gain_db *= 0.98
        else:
            rms_db = _db(math.sqrt(float(np.mean(x * x)) + 1e-12))
            if rms_db > -50:
                err = target_db - (rms_db + self.gain_db)
                self.gain_db += max(-0.3, min(0.15, err * 0.02))
                self.gain_db = max(-12.0, min(12.0, self.gain_db))
        return x * (10 ** (self.gain_db / 20))


# --------------------------------------------------------------------------
# Presets (karaoke-oriented)
# --------------------------------------------------------------------------

FLAT = {k: 0.0 for k, *_ in EQ_BANDS}


def _eq(**kw):
    d = dict(FLAT)
    d.update(kw)
    return d


PRESETS = {
    "Natural": dict(lowcut=80, eq=_eq(), echo_mix=0.0, echo_ms=180, echo_fb=0.3, echo_damp=0.3,
                    reverb_mix=0.0, reverb_room=0.4, reverb_damp=0.5, comp=True, comp_thr=-14, comp_ratio=2.5),
    "Karaoke Classic": dict(lowcut=100, eq=_eq(b250=-2, b2k5=2, b5k=1.5), echo_mix=0.22, echo_ms=170, echo_fb=0.35,
                            echo_damp=0.35, reverb_mix=0.15, reverb_room=0.5, reverb_damp=0.5,
                            comp=True, comp_thr=-16, comp_ratio=3),
    "KTV Echo": dict(lowcut=110, eq=_eq(b250=-2, b2k5=2.5, b5k=2), echo_mix=0.35, echo_ms=230, echo_fb=0.48,
                     echo_damp=0.45, reverb_mix=0.2, reverb_room=0.6, reverb_damp=0.5,
                     comp=True, comp_thr=-16, comp_ratio=3),
    "Concert Hall": dict(lowcut=90, eq=_eq(b250=-1, b2k5=1.5, b10k=1), echo_mix=0.0, echo_ms=200, echo_fb=0.3,
                         echo_damp=0.3, reverb_mix=0.32, reverb_room=0.85, reverb_damp=0.35,
                         comp=True, comp_thr=-16, comp_ratio=3),
    "Stadium": dict(lowcut=120, eq=_eq(b250=-2, b2k5=2, b5k=1), echo_mix=0.2, echo_ms=340, echo_fb=0.3,
                    echo_damp=0.5, reverb_mix=0.35, reverb_room=0.95, reverb_damp=0.4,
                    comp=True, comp_thr=-18, comp_ratio=4),
    "Warm Vocal": dict(lowcut=80, eq=_eq(b100=2, b250=1, b5k=-1, b10k=-1.5), echo_mix=0.1, echo_ms=150,
                       echo_fb=0.25, echo_damp=0.6, reverb_mix=0.18, reverb_room=0.5, reverb_damp=0.7,
                       comp=True, comp_thr=-16, comp_ratio=3),
    "Bright Pop": dict(lowcut=110, eq=_eq(b250=-2.5, b800=-1, b5k=3, b10k=2.5), echo_mix=0.14, echo_ms=120,
                       echo_fb=0.25, echo_damp=0.2, reverb_mix=0.22, reverb_room=0.6, reverb_damp=0.3,
                       comp=True, comp_thr=-18, comp_ratio=4),
    "Speech / MC": dict(lowcut=130, eq=_eq(b250=-2, b2k5=2), echo_mix=0.0, echo_ms=150, echo_fb=0.2, echo_damp=0.3,
                        reverb_mix=0.0, reverb_room=0.3, reverb_damp=0.5, comp=True, comp_thr=-20, comp_ratio=5),
}


class VoiceChain:
    """Full per-mic processing. Takes mono float block, returns (L, R)."""

    def __init__(self, fs):
        self.fs = fs
        self.eq = Equalizer(fs)
        self.echo = Echo(fs)
        self.reverb = Reverb(fs)
        self.gate = Gate()
        self.comp = Compressor()
        self.agc = AutoGain()
        self.p = None

    def configure(self, p):
        self.p = p
        self.eq.configure(p["lowcut"], p["eq"])
        self.echo.configure(p["echo_ms"], p["echo_fb"], p["echo_damp"])
        self.reverb.configure(p["reverb_room"], p["reverb_damp"])

    def process(self, x, gain_db, auto_gain, gate_on, gate_db, pan):
        p = self.p
        x = x.astype(np.float64) * (10 ** (gain_db / 20))
        x = self.agc.process(x, auto_gain)
        level = x.copy()  # for meters (post gain, pre-FX)
        x = self.gate.process(x, gate_db, gate_on)
        x = self.eq.process(x)
        x = self.comp.process(x, p["comp_thr"], p["comp_ratio"], p["comp"])
        l = x.copy()
        r = x.copy()
        if p["echo_mix"] > 0.001:
            e = self.echo.process(x) * p["echo_mix"]
            l += e
            r += e
        if p["reverb_mix"] > 0.001:
            rl, rr = self.reverb.process(x)
            l += rl * p["reverb_mix"] * 3
            r += rr * p["reverb_mix"] * 3
        # constant-power pan, pan in [-1, 1]
        ang = (pan + 1) * math.pi / 4
        return l * math.cos(ang) * 1.414, r * math.sin(ang) * 1.414, level
