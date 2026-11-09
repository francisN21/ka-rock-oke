import { LibraryList } from "./SearchScreen.jsx";

export default function MineScreen({ name, mine, popular, actions, onRename }) {
  return (
    <>
      <section className="stage" style={{ marginTop: 6 }}>
        <div className="singer wide">{name}</div>
        <div className="section-head" style={{ marginTop: 6 }}>
          <span className="muted">This name follows you on this phone.</span>
          <button className="link" onClick={onRename}>Change name</button>
        </div>
      </section>

      <section>
        <h2 className="wide">Starred</h2>
        {!mine ? <p className="note">Loading…</p>
          : mine.favourites.length ? <LibraryList songs={mine.favourites} actions={actions} />
          : <p className="note">Tap the star on any downloaded song to keep it here.</p>}
      </section>

      <section>
        <h2 className="wide">You sang recently</h2>
        {!mine ? <p className="note">Loading…</p>
          : mine.recent.length ? <LibraryList songs={mine.recent} actions={actions} />
          : <p className="note">Songs you finish singing show up here.</p>}
      </section>

      {popular.length > 0 && (
        <section>
          <h2 className="wide">Popular here</h2>
          <LibraryList songs={popular} actions={actions} />
        </section>
      )}
    </>
  );
}
