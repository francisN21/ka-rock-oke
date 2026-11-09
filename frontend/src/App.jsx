import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getName, setName as saveName } from "./api.js";
import { useParty, turnFor } from "./useParty.js";
import { Icons, NameSheet, Toasts } from "./components/ui.jsx";
import QueueScreen from "./screens/QueueScreen.jsx";
import SearchScreen from "./screens/SearchScreen.jsx";
import MineScreen from "./screens/MineScreen.jsx";

const TABS = [
  { id: "queue", label: "Queue", icon: Icons.queue },
  { id: "find", label: "Find songs", icon: Icons.search },
  { id: "mine", label: "My songs", icon: Icons.mine },
];

function initialTab() {
  const h = window.location.hash.replace("#", "");
  return TABS.some((t) => t.id === h) ? h : "queue";
}

export default function App() {
  const [name, setNameState] = useState(getName());
  const [renaming, setRenaming] = useState(false);
  const [tab, setTab] = useState(initialTab);
  const [toasts, setToasts] = useState([]);
  const [pending, setPending] = useState({}); // path or video id -> "busy" | "downloading"
  const [popular, setPopular] = useState([]);
  const [mine, setMine] = useState(null);
  const [stars, setStars] = useState({}); // path -> starred, ahead of the next list refresh

  const toast = useCallback((text, kind = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t.slice(-2), { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3800);
  }, []);

  const party = useParty(useCallback(() => {}, []));
  const { queue, now, downloads, connected, readyIds } = party;

  const loadLists = useCallback(() => {
    api.popular().then((r) => setPopular(r.songs)).catch(() => {});
    api.me().then(setMine).catch(() => {});
  }, []);
  useEffect(loadLists, [loadLists, name]);

  useEffect(() => {
    const onHash = () => setTab(initialTab());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = (id) => {
    setTab(id);
    history.replaceState(null, "", `#${id}`);
    window.scrollTo({ top: 0 });
  };

  const queuedPaths = useMemo(() => new Set(queue.map((q) => q.file)), [queue]);

  const actions = useMemo(() => ({
    stateOf(key) {
      if (queuedPaths.has(key)) return "queued";
      return pending[key] || "idle";
    },
    async queueLocal(song) {
      setPending((p) => ({ ...p, [song.path]: "busy" }));
      try {
        await api.enqueue(song.path, name);
        await party.refreshQueue();
        toast(`Added ${song.title}`);
      } catch (e) {
        toast(e.message, "danger");
      } finally {
        setPending((p) => { const n = { ...p }; delete n[song.path]; return n; });
      }
    },
    async queueYouTube(video) {
      setPending((p) => ({ ...p, [video.video_id]: "busy" }));
      try {
        await api.download(video, name);
        setPending((p) => ({ ...p, [video.video_id]: "downloading" }));
        party.refreshDownloads();
        toast("Downloading. It joins the queue when it's ready.");
      } catch (e) {
        setPending((p) => { const n = { ...p }; delete n[video.video_id]; return n; });
        toast(e.message, "danger");
      }
    },
    isStarred(song) {
      return stars[song.path] ?? song.favourite;
    },
    async star(song) {
      const was = stars[song.path] ?? song.favourite;
      setStars((s) => ({ ...s, [song.path]: !was }));
      try {
        await api.favourite(song.path, !was, name);
        loadLists();
      } catch (e) {
        setStars((s) => ({ ...s, [song.path]: was }));
        toast(e.message, "danger");
      }
    },
  }), [queuedPaths, pending, name, party, toast, loadLists, stars]);

  // A downloaded video's button stops saying "Downloading" once it lands.
  useEffect(() => {
    setPending((p) => {
      let changed = false;
      const n = { ...p };
      for (const id of Object.keys(readyIds)) if (n[id]) { delete n[id]; changed = true; }
      return changed ? n : p;
    });
  }, [readyIds]);

  const t = turnFor(name, queue, now);
  const badge = t.state === "waiting" ? (t.ahead === 0 ? "!" : t.ahead) : null;

  const onSaveName = (n) => {
    saveName(n);
    setNameState(n);
    setRenaming(false);
  };

  return (
    <div className="shell">
      <header className="top">
        <h1 className="brand wide">Ka-Rock<span>-oke</span></h1>
        {name && (
          <button className="who" onClick={() => setRenaming(true)} aria-label={`Signed in as ${name}. Change name`}>
            <i>{name.slice(0, 1).toUpperCase()}</i><b>{name}</b>
          </button>
        )}
      </header>
      {!connected && <p className="offline">Reconnecting to the karaoke PC…</p>}

      <main>
        {tab === "queue" && <QueueScreen name={name} queue={queue} now={now} downloads={downloads} onFind={() => go("find")} />}
        {tab === "find" && <SearchScreen actions={actions} readyIds={readyIds} popular={popular} />}
        {tab === "mine" && <MineScreen name={name} mine={mine} popular={popular} actions={actions} onRename={() => setRenaming(true)} />}
      </main>

      <nav className="tabs" aria-label="Sections">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} aria-current={tab === id ? "page" : undefined} onClick={() => go(id)}>
            <Icon />
            {id === "queue" && badge != null && <span className="badge" aria-hidden="true">{badge}</span>}
            {label}
          </button>
        ))}
      </nav>

      <Toasts items={toasts} />
      {(!name || renaming) && (
        <NameSheet current={renaming ? name : ""} onSave={onSaveName} onCancel={renaming ? () => setRenaming(false) : null} />
      )}
    </div>
  );
}
