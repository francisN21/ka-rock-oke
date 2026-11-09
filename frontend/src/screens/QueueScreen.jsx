import { turnFor } from "../useParty.js";

const fmt = (s) => {
  if (s == null || !isFinite(s)) return null;
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

function TurnSign({ name, queue, now, onFind }) {
  const t = turnFor(name, queue, now);
  if (t.state === "singing") {
    return (
      <div className="turn singing">
        <div className="num" aria-hidden="true">Now</div>
        <div className="line1">You're on. Sing it!</div>
        <div className="line2">{t.title}</div>
      </div>
    );
  }
  if (t.state === "waiting") {
    const next = t.ahead === 0;
    return (
      <div className="turn" aria-label={next ? "You're next" : `${t.ahead} songs before your turn`}>
        <div className="num">{next ? "Next" : t.ahead}</div>
        <div className="line1">{next ? "You're up next" : t.ahead === 1 ? "song before your turn" : "songs before your turn"}</div>
        <div className="line2">{t.title}{t.queued > 1 ? `, plus ${t.queued - 1} more of yours` : ""}</div>
      </div>
    );
  }
  return (
    <div className="turn plain">
      <div className="line1">You're not in line yet</div>
      <div className="line2">Pick a song and it joins the running order. Singers take turns.</div>
      <button className="btn primary cta" onClick={onFind}>Find a song</button>
    </div>
  );
}

function NowSinging({ now, name }) {
  if (!now?.now_playing) {
    return <div className="stage empty-stage">Nobody's singing right now.</div>;
  }
  const pos = now.now_playing_position, dur = now.now_playing_duration;
  const pct = dur ? Math.min(100, (pos / dur) * 100) : 0;
  const mine = now.now_playing_user?.toLowerCase() === name.toLowerCase();
  return (
    <div className="stage">
      <div className="singer wide">{now.now_playing_user || "Someone"} {mine && <span className="tag you">You</span>}</div>
      <div className="song">{now.now_playing}</div>
      <div className="meta">
        {now.is_paused && <span className="tag">Paused</span>}
        <span>{fmt(pos) || "0:00"}</span>
        <div className="bar" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin="0" aria-valuemax="100"><i style={{ width: `${pct}%` }} /></div>
        <span>{fmt(dur) || "--:--"}</span>
      </div>
    </div>
  );
}

function Downloads({ downloads }) {
  const { active, pending = [], errors = [] } = downloads;
  if (!active && !pending.length && !errors.length) return null;
  return (
    <section>
      <h2 className="wide">Getting songs ready</h2>
      <div className="downloads">
        {active && (
          <div className="dl">
            <div>{active.title} <span className="muted">for {active.user}</span></div>
            <div className="bar"><i style={{ width: `${active.progress || 0}%` }} /></div>
          </div>
        )}
        {pending.map((p, i) => <div className="dl muted" key={i}>Waiting: {p.title || p.video_url}</div>)}
        {errors.map((e) => <div className="dl err" key={e.id}>Couldn't download {e.title}</div>)}
      </div>
    </section>
  );
}

export default function QueueScreen({ name, queue, now, downloads, onFind }) {
  const me = name.toLowerCase();
  return (
    <>
      <TurnSign name={name} queue={queue} now={now} onFind={onFind} />
      <section>
        <h2 className="wide">On stage</h2>
        <NowSinging now={now} name={name} />
      </section>
      <section>
        <div className="section-head">
          <h2 className="wide">Running order</h2>
          <span className="muted">{queue.length ? `${queue.length} song${queue.length > 1 ? "s" : ""}` : ""}</span>
        </div>
        {queue.length === 0 ? (
          <p className="note">The queue is empty. Add a song and you'll be first.</p>
        ) : (
          <ol className="order">
            {queue.map((item, i) => {
              const mine = item.user?.toLowerCase() === me;
              return (
                <li key={item.file} className={mine ? "mine" : ""}>
                  <span className="pos">{i + 1}</span>
                  <span className="name"><b>{item.user}</b>{mine && <span className="tag you">You</span>}</span>
                  <span className="title">{item.title}{item.semitones ? ` (key ${item.semitones > 0 ? "+" : ""}${item.semitones})` : ""}</span>
                </li>
              );
            })}
          </ol>
        )}
      </section>
      <Downloads downloads={downloads} />
    </>
  );
}
