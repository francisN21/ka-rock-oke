// Thin wrappers over PiKaraoke's endpoints. Identity is the same "user" cookie the
// original pages use, so a guest keeps their name across both front ends.

const COOKIE = "user";

export function getName() {
  const hit = document.cookie.split("; ").find((c) => c.startsWith(COOKIE + "="));
  if (!hit) return "";
  try {
    return decodeURIComponent(hit.slice(COOKIE.length + 1)).trim();
  } catch {
    return "";
  }
}

export function setName(name) {
  const tenYears = 60 * 60 * 24 * 3650;
  document.cookie = `${COOKIE}=${encodeURIComponent(name)}; path=/; max-age=${tenYears}; SameSite=Lax`;
}

async function request(url, options) {
  const res = await fetch(url, { credentials: "same-origin", ...options });
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const msg = body?.errors ? Object.values(body.errors).flat().join(" ") : body?.error || res.statusText;
    throw new Error(msg || "Request failed");
  }
  return body;
}

const get = (url) => request(url);
const postForm = (url, data) => request(url, { method: "POST", body: new URLSearchParams(data) });
const postJSON = (url, data) =>
  request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

/** PiKaraoke answers queue adds with success: [ok, message]. */
function checkPair(body) {
  const [ok, message] = Array.isArray(body?.success) ? body.success : [body?.success, ""];
  if (!ok) throw new Error(message || "That didn't work");
  return message;
}

export const api = {
  queue: () => get("/api/get_queue"),
  nowPlaying: () => get("/api/now_playing"),
  downloads: () => get("/api/queue/downloads"),
  search: (q, nonKaraoke = false) =>
    get(`/api/app/search?q=${encodeURIComponent(q)}&non_karaoke=${nonKaraoke}`),
  library: (q = "", offset = 0, limit = 50) =>
    get(`/api/app/library?q=${encodeURIComponent(q)}&offset=${offset}&limit=${limit}`),
  popular: () => get("/api/app/popular"),
  me: () => get("/api/app/me"),
  enqueue: async (path, name) =>
    checkPair(await postForm("/api/enqueue", { song_to_add: path, song_added_by: name })),
  download: (video, name) =>
    postJSON("/api/download", { song_url: video.url, song_added_by: name, song_title: video.title, queue: true }),
  favourite: async (path, starred, name) => {
    const body = await postForm("/api/singer/favourite", { song: path, starred, song_added_by: name });
    if (!body?.success) throw new Error(body?.error || "Couldn't save that star");
    return body;
  },
};

export const NAME_MAX = 30;
