import { useCallback, useEffect, useRef, useState } from "react";
import { io } from "socket.io-client";
import { api } from "./api.js";

/**
 * Live room state: queue, now playing and downloads, kept fresh by PiKaraoke's
 * socket events. The server only says "the queue moved", so we refetch on those.
 */
export function useParty(onNotice) {
  const [queue, setQueue] = useState([]);
  const [now, setNow] = useState(null);
  const [downloads, setDownloads] = useState({ active: null, pending: [], errors: [] });
  const [connected, setConnected] = useState(false);
  const [readyIds, setReadyIds] = useState({});
  const notice = useRef(onNotice);
  notice.current = onNotice;

  const refreshQueue = useCallback(() => api.queue().then(setQueue).catch(() => {}), []);
  const refreshNow = useCallback(
    () => api.nowPlaying().then((n) => n && setNow(n)).catch(() => {}),
    []
  );
  const refreshDownloads = useCallback(
    () => api.downloads().then((d) => d && setDownloads(d)).catch(() => {}),
    []
  );

  useEffect(() => {
    refreshQueue();
    refreshNow();
    refreshDownloads();
    const socket = io({ path: "/socket.io", transports: ["websocket", "polling"] });
    socket.on("connect", () => {
      setConnected(true);
      refreshQueue();
      refreshNow();
      refreshDownloads();
    });
    socket.on("disconnect", () => setConnected(false));
    socket.on("now_playing", (n) => n && setNow(n));
    socket.on("queue_update", refreshQueue);
    socket.on("download_started", refreshDownloads);
    socket.on("download_stopped", refreshDownloads);
    socket.on("song_downloaded", (d) => {
      if (d?.youtube_id) setReadyIds((r) => ({ ...r, [d.youtube_id]: d.path }));
      refreshDownloads();
    });
    socket.on("notification", (raw) => {
      const [text, cls] = String(raw).split("::");
      notice.current?.(text, (cls || "").replace("is-", ""));
    });
    // Download progress isn't pushed, so poll while something is downloading.
    const poll = setInterval(refreshDownloads, 2000);
    return () => {
      clearInterval(poll);
      socket.close();
    };
  }, [refreshQueue, refreshNow, refreshDownloads]);

  return { queue, now, downloads, connected, readyIds, refreshQueue, refreshDownloads };
}

/** Where a singer stands: singing now, songs ahead of them, or not in line. */
export function turnFor(name, queue, now) {
  const me = name.trim().toLowerCase();
  if (!me) return { state: "anonymous" };
  const singingNow = now?.now_playing && now.now_playing_user?.toLowerCase() === me;
  const index = queue.findIndex((item) => item.user?.toLowerCase() === me);
  const mine = queue.filter((item) => item.user?.toLowerCase() === me).length;
  if (singingNow) return { state: "singing", title: now.now_playing, queued: mine };
  if (index === -1) return { state: "none" };
  return { state: "waiting", ahead: index, title: queue[index].title, queued: mine };
}
