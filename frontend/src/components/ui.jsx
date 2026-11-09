import { useState } from "react";
import { NAME_MAX } from "../api.js";

const icon = (d) => (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
       strokeLinejoin="round" aria-hidden="true" {...props}>{d}</svg>
);

export const Icons = {
  queue: icon(<><path d="M4 6h11M4 12h11M4 18h7" /><circle cx="18.5" cy="16.5" r="2.5" /><path d="M21 16.5V7l-3 1" /></>),
  search: icon(<><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>),
  mine: icon(<><path d="M12 15a3.5 3.5 0 0 0 3.5-3.5v-5a3.5 3.5 0 1 0-7 0v5A3.5 3.5 0 0 0 12 15Z" /><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5V21" /></>),
  star: (filled) => (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.8Z" />
    </svg>
  ),
};

/** One song with an add button; a star when it's already downloaded. */
export function SongRow({ title, sub = [], starred, onStar, action }) {
  return (
    <div className="song-row">
      <div>
        <div className="t">{title}</div>
        {sub.filter(Boolean).length > 0 && (
          <div className="s">{sub.filter(Boolean).map((s, i) => <span key={i}>{s}</span>)}</div>
        )}
      </div>
      <div className="acts">
        {onStar && (
          <button className="star" aria-pressed={!!starred} onClick={onStar}
                  aria-label={starred ? "Remove star" : "Star this song"}>
            {Icons.star(starred)}
          </button>
        )}
        {action}
      </div>
    </div>
  );
}

/** Add button that walks through its states: Add -> Adding -> Queued / Downloading. */
export function AddButton({ state, onClick, label = "Add" }) {
  if (state === "busy") return <button className="btn small" disabled><span className="spinner" /> Adding</button>;
  if (state === "queued") return <span className="btn small done">Queued</span>;
  if (state === "downloading") return <span className="btn small done">Downloading</span>;
  return <button className="btn small primary" onClick={onClick}>{label}</button>;
}

export function NameSheet({ current, onSave, onCancel }) {
  const [value, setValue] = useState(current || "");
  const clean = value.trim();
  const valid = clean.length > 0 && clean.length <= NAME_MAX && !/[<>]/.test(clean);
  return (
    <div className="sheet-wrap" role="dialog" aria-modal="true" aria-labelledby="name-title">
      <form className="sheet" onSubmit={(e) => { e.preventDefault(); if (valid) onSave(clean); }}>
        <h2 id="name-title" className="wide">{current ? "Change your name" : "What should we call you?"}</h2>
        <p>Shown on the TV next to the songs you add, so everyone knows who's up.</p>
        <label className="sr-only" htmlFor="name-input">Your name</label>
        <input id="name-input" autoFocus maxLength={NAME_MAX} autoComplete="nickname"
               placeholder="Your name" value={value} onChange={(e) => setValue(e.target.value)} />
        <div className="row">
          {onCancel && <button type="button" className="btn" onClick={onCancel}>Cancel</button>}
          <button className="btn primary" disabled={!valid}>{current ? "Save name" : "Start singing"}</button>
        </div>
      </form>
    </div>
  );
}

export function Toasts({ items }) {
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => <div key={t.id} className={`toast ${t.kind === "danger" ? "danger" : ""}`}>{t.text}</div>)}
    </div>
  );
}
