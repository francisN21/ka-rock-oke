import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { AddButton, SongRow } from "../components/ui.jsx";

/** Songs already downloaded: queue straight away, and starrable. */
export function LibraryList({ songs, actions }) {
  return (
    <ul className="songs">
      {songs.map((s) => (
        <li key={s.path}>
          <SongRow
            title={s.title}
            sub={[s.plays ? `Sung ${s.plays} time${s.plays > 1 ? "s" : ""}` : null]}
            starred={actions.isStarred(s)}
            onStar={() => actions.star(s)}
            action={<AddButton state={actions.stateOf(s.path)} onClick={() => actions.queueLocal(s)} />}
          />
        </li>
      ))}
    </ul>
  );
}

function YouTubeResults({ results, actions, readyIds }) {
  return (
    <ul className="songs">
      {results.map((r) => {
        const local = r.library_path || readyIds[r.video_id];
        return (
          <li key={r.video_id}>
            <SongRow
              title={r.title}
              sub={[r.channel, r.duration, local ? "Downloaded" : null]}
              action={
                <AddButton
                  state={local ? actions.stateOf(local) : actions.stateOf(r.video_id)}
                  onClick={() => (local ? actions.queueLocal({ path: local, title: r.title }) : actions.queueYouTube(r))}
                />
              }
            />
          </li>
        );
      })}
    </ul>
  );
}

export default function SearchScreen({ actions, readyIds, popular }) {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("youtube");
  const [nonKaraoke, setNonKaraoke] = useState(false);
  const [yt, setYt] = useState(null);
  const [lib, setLib] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  const reqId = useRef(0);

  const runYouTube = async (e) => {
    e?.preventDefault();
    const term = q.trim();
    if (!term) return;
    inputRef.current?.blur();
    const id = ++reqId.current;
    setBusy(true); setError("");
    try {
      const r = await api.search(term, nonKaraoke);
      if (id === reqId.current) setYt(r.results);
    } catch (err) {
      if (id === reqId.current) setError(`Search failed: ${err.message}. Check the PC is online and try again.`);
    } finally {
      if (id === reqId.current) setBusy(false);
    }
  };

  // The library is local, so it filters as you type.
  useEffect(() => {
    if (source !== "library") return;
    const id = ++reqId.current;
    const t = setTimeout(() => {
      api.library(q.trim(), 0, 100).then((r) => id === reqId.current && setLib(r)).catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [q, source]);

  const loadMore = () =>
    api.library(q.trim(), lib.songs.length, 100).then((r) => setLib({ ...r, songs: [...lib.songs, ...r.songs] }));

  return (
    <>
      <form className="searchbar" role="search" onSubmit={source === "youtube" ? runYouTube : (e) => e.preventDefault()}>
        <label className="sr-only" htmlFor="q">Song or artist</label>
        <input id="q" ref={inputRef} type="search" enterKeyHint="search" autoComplete="off"
               placeholder={source === "youtube" ? "Song or artist" : "Filter downloaded songs"}
               value={q} onChange={(e) => setQ(e.target.value)} />
        {source === "youtube" && <button className="btn primary" disabled={!q.trim() || busy}>Search</button>}
      </form>
      <div className="opts">
        <div className="seg" role="group" aria-label="Where to look">
          <button type="button" aria-pressed={source === "youtube"} onClick={() => setSource("youtube")}>YouTube</button>
          <button type="button" aria-pressed={source === "library"} onClick={() => setSource("library")}>Downloaded</button>
        </div>
        {source === "youtube" && (
          <label className="check">
            <input type="checkbox" checked={nonKaraoke} onChange={(e) => setNonKaraoke(e.target.checked)} />
            Include non-karaoke videos
          </label>
        )}
      </div>

      {source === "youtube" && (
        <section aria-live="polite">
          {busy && <p className="note">Searching YouTube…</p>}
          {error && <p className="err-text">{error}</p>}
          {!busy && yt && yt.length === 0 && <p className="note">No results. Try the artist name, or include non-karaoke videos.</p>}
          {!busy && yt && yt.length > 0 && <YouTubeResults results={yt} actions={actions} readyIds={readyIds} />}
          {!yt && !busy && popular.length > 0 && (
            <>
              <h2 className="wide">Popular here</h2>
              <LibraryList songs={popular} actions={actions} />
            </>
          )}
          {!yt && !busy && popular.length === 0 && (
            <p className="note">Search for a song. New songs download to the PC first, then join the queue automatically.</p>
          )}
        </section>
      )}

      {source === "library" && (
        <section>
          {!lib && <p className="note">Loading…</p>}
          {lib && (
            <>
              <p className="note">{lib.total} song{lib.total === 1 ? "" : "s"}{q.trim() ? " match" : " on the PC"}</p>
              <LibraryList songs={lib.songs} actions={actions} />
              {lib.songs.length < lib.total && <button className="btn more" onClick={loadMore}>Show more</button>}
            </>
          )}
        </section>
      )}
    </>
  );
}
