# Ka-Rock-oke

A fork of [PiKaraoke](https://github.com/vicwomg/pikaraoke) for a home theater HTPC.
PiKaraoke's Python backend is kept as-is so upstream updates can still be merged;
the fork adds:

| Folder | What |
|---|---|
| `frontend/` | New phone app (React + Vite). Served by PiKaraoke at `/app/`. `frontend/dist` is committed, so the HTPC doesn't need Node. |
| `micbridge/` | Low-latency mic mixer with effects, meters and a delay test. Settings at http://localhost:5556 |
| `pikaraoke/routes/app_api.py` | JSON endpoints the app needs (search, library, popular, my songs) and the `/app/` route. |

## Run it (Windows)

1. `setup_windows.bat` once (installs Python 3.13, ffmpeg, and everything else).
2. `start_karaoke.bat`.
3. Phones on the same Wi-Fi open `http://<PC address>:5555/app/`.

## Working on the app

```
cd frontend
npm install
npm run dev        # proxies to a PiKaraoke on localhost:5555
npm run build      # writes frontend/dist, served at /app/
```

## Keeping up with PiKaraoke

```
git remote add upstream https://github.com/vicwomg/pikaraoke.git   # once
git fetch upstream
git merge upstream/master
```
Upstream files the fork touches: `pikaraoke/routes/__init__.py` (registers `app_api`),
`tests/unit/test_auth_gate.py` (lists its public endpoints), `.gitignore`.
