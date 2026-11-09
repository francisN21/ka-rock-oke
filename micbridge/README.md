# Ka-Rock-oke! — HTPC karaoke

Two programs working together:

| Piece | Job | Port |
|---|---|---|
| **PiKaraoke** (open source, `pip install pikaraoke`) | YouTube search, phones queue songs by scanning a QR code on the TV, singer names, fair rotation, key change | 5555 |
| **MicBridge** (this folder) | Any mic (USB, 3.5 mm, wireless receiver, podcast interface) → low-latency passthrough to the speakers, with echo/reverb/EQ, meters, mic test and a delay meter | 5556 |

## Setup (once)

MicBridge lives inside the Ka-Rock-oke repo and shares its Python environment.
From the repo root: run `setup_windows.bat`, then `start_karaoke.bat`.
To run MicBridge alone: `micbridge\run_micbridge.bat`.

**Turn OFF** Windows *Listen to this device* on your mic (Sound settings, Recording, mic, Listen), or you'll hear yourself twice.

## Settings page (http://localhost:5556)

- **Speaker** — output device, *Test speaker*, level meter, output volume, send vocals to Front / **Center** / Front+Center (center keeps the voice on the TV in 5.1).
- **Microphones** — one card per mic (add as many as you like; each can be a different device). Device + channel pickers, *Test microphone* (records 4 s, plays it back with effects, tells you if the level is too hot or quiet), input volume, *Automatically adjust microphone volume*, mute.
- **Effects** — presets: Natural, Karaoke Classic, KTV Echo, Concert Hall, Stadium, Warm Vocal, Bright Pop, Speech/MC. Echo and Reverb sliders up front; 6-band EQ, echo time/repeats, room size, low-cut, compressor, noise gate and pan under *Equalizer & advanced*.
- **Delay** — live software delay, plus **Measure delay**: plays 3 clicks and times when the mic hears them. This measures your *whole* chain (software + sound card + optical + AV receiver), which is the number that matters.
- **Rescan devices** after plugging in a new receiver. Devices are remembered by name, so unplugging/replugging is fine.

Run `run_micbridge.bat --lan` if you want to open the settings page from a phone/tablet (admin use only — don't share it with guests).

## Getting rid of the mic delay

Why Windows "Listen to this device" lags: it goes through the shared Windows mixer twice with large buffers (often 30–60 ms+). MicBridge opens the mic in WASAPI **exclusive** mode with 128-sample buffers, so the software adds roughly **8–12 ms**.

But in your setup the biggest delay is probably **downstream of the PC**:

1. **Optical + 5.1 = Dolby Digital Live encoding.** Optical can only carry 2-channel PCM *or* compressed 5.1. The X-Fi's DDL encoder plus the receiver's decoder add tens of ms. Test both: set the card to stereo PCM (no DDL) and run *Measure delay*, then DDL on. If stereo PCM is much faster, use it for karaoke nights — the receiver's Dolby Pro Logic II / Neural:X upmixer can still fill all 5.1 speakers (with a small processing cost of its own).
2. **AV receiver DSP.** Put the receiver in **Direct / Pure Direct / Game** mode and turn off room correction (Audyssey/YPAO/Dirac) and "lip sync" delay for karaoke.
3. **X-Fi driver.** The Titanium has an ASIO driver. If you pick an **ASIO** output in MicBridge it switches to one full-duplex ASIO stream (lowest possible software delay) — but then mics must plug into the X-Fi's own mic/line jack. Try buffer 64 or 128.
4. Buffer size: drop to 64 if you hear no crackles; raise to 256 if you do.

Rough guide: under ~20 ms total feels instant, 20–35 ms is fine for most singers, over ~40 ms feels like singing in a canyon. If the whole-system number stays high even with stereo PCM + Direct mode, the bullet-proof fix is a small analog mixer (~$40) that sums the PC's analog out and the mic receiver *before* the receiver's analog input — zero-latency mic, but you lose the PC's 5.1 for that input.

## "Who queued what"

PiKaraoke asks each phone for a name the first time and remembers it on that phone. Every queue entry shows the singer, and **Fair queue** (Info/Settings page) rotates singers in rounds so one person can't take over. There's also a per-singer song limit and *KJ mode* for queueing on behalf of someone without a phone.

YouTube sign-in isn't used for this: a page on your PC can't see someone's YouTube login, and wiring up Google sign-in would need a Google Cloud OAuth app — a lot of hassle for what the name prompt already does. It can be added later if you really want it.

Note: PiKaraoke downloads videos with yt-dlp. That's a grey area under YouTube's Terms of Service; fine for private home use, don't run it as a public/paid venue.

## Hardware notes

- **USB wireless receivers** show up in Windows as a normal USB microphone (USB Audio Class, no driver) — MicBridge sees them automatically. Best option: one receiver per mic, or a dual-channel receiver (appears as 1 stereo device: Mic A = left channel, Mic B = right channel; add two mic cards on the same device and set Channel 1 / Channel 2).
- **Receivers with a 6.35 mm (1/4") plug** need a 1/4"→3.5 mm adapter into the X-Fi's mic/line-in, or a cheap USB audio adapter / USB interface. Line-level receivers into a PC *mic* jack can clip — use line-in or turn the receiver down.
- **Podcast gear** (USB interfaces like Focusrite/Behringer/FIFINE) works as-is; pick the interface and the input channel your mic is on.
- Point mics away from the speakers and keep echo/reverb moderate to avoid feedback. The noise gate helps between lines.

## Files

```
micbridge/dsp.py      EQ, echo, reverb (Freeverb-style), gate, compressor, auto-gain, presets
micbridge/engine.py   device discovery, WASAPI/ASIO streams, mixing, routing, tests
micbridge/app.py      settings web server
micbridge/static/     settings page
```
Settings are saved to `%USERPROFILE%\.micbridge\settings.json`.
