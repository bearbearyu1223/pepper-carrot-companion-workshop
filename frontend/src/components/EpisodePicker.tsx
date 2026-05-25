import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Episode } from '../api/types';

interface EpisodePickerProps {
  onSelect: (episode: Episode) => void;
}

export function EpisodePicker({ onSelect }: EpisodePickerProps) {
  const [episodes, setEpisodes] = useState<Episode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listEpisodes()
      .then((res) => setEpisodes(res.episodes))
      .catch((err) => setError(String(err)));
  }, []);

  if (error) return <div className="error">Failed to load episodes: {error}</div>;
  if (!episodes) return <div className="loading">Loading episodes…</div>;

  return (
    <div className="episode-picker">
      <header className="picker-hero">
        <div className="picker-hero__inner">
          <p className="picker-hero__eyebrow">A reading companion for</p>
          <h1 className="picker-hero__title">Pepper&amp;Carrot</h1>
          <p className="picker-hero__subtitle">
            Step into the world of Hereva alongside a young Chaosah witch and
            her impulsive cat. Pick an episode below to start reading. The
            chat-with-the-page companion lands in later posts of the series.
          </p>
          <p className="picker-hero__attribution">
            Comic by{' '}
            <a
              href="https://www.peppercarrot.com"
              target="_blank"
              rel="noreferrer"
            >
              David Revoy
            </a>{' '}
            · CC BY 4.0
          </p>
        </div>
      </header>
      <ul className="episode-grid">
        {episodes.map((ep) => (
          <li key={ep.id}>
            <EpisodeCard episode={ep} onOpen={() => onSelect(ep)} />
          </li>
        ))}
      </ul>
    </div>
  );
}

// Threshold above which the summary gets a "Read more" toggle. Below this,
// the full text fits within the clamped display (~3 lines) and there's no
// point hiding part of it.
const SUMMARY_CLAMP_THRESHOLD = 180;

interface EpisodeCardProps {
  episode: Episode;
  onOpen: () => void;
}

function EpisodeCard({ episode: ep, onOpen }: EpisodeCardProps) {
  const [expanded, setExpanded] = useState(false);
  const summary = ep.plot_summary ?? '';
  const needsToggle = summary.length > SUMMARY_CLAMP_THRESHOLD;

  // The whole card is one click target (opens the episode) except the
  // "Read more" toggle inside the summary, which uses stopPropagation.
  // Using a div + role=button + keyboard handler so the inner toggle can be
  // a real <button> without triggering the nested-interactive-elements bug.
  const handleKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen();
    }
  };

  return (
    <div
      className="episode-card"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={handleKey}
      aria-label={`Open episode ${ep.episode_number}: ${ep.title}`}
    >
      <div className="episode-card__cover">
        {ep.cover_image_url ? (
          <img src={ep.cover_image_url} alt="" />
        ) : (
          <div className="episode-cover-placeholder" aria-hidden="true" />
        )}
        <span className="episode-card__badge">
          Episode {ep.episode_number}
        </span>
      </div>
      <div className="episode-card__body">
        <h2 className="episode-card__title">{ep.title}</h2>
        {summary ? (
          <div className="episode-card__summary-wrap">
            <p
              className={
                'episode-card__summary' +
                (needsToggle && !expanded ? ' is-clamped' : '')
              }
            >
              {summary}
            </p>
            {needsToggle && (
              <button
                type="button"
                className="episode-card__more"
                onClick={(e) => {
                  e.stopPropagation();
                  setExpanded((v) => !v);
                }}
                aria-expanded={expanded}
              >
                {expanded ? 'Show less' : 'Read more'}
              </button>
            )}
          </div>
        ) : (
          <p className="episode-card__summary episode-card__summary--placeholder">
            Not yet ingested. Run the ingest-from-images skill to unlock this
            episode.
          </p>
        )}
        <div className="episode-card__footer">
          <span className="episode-card__pages">
            {ep.page_count} {ep.page_count === 1 ? 'page' : 'pages'}
          </span>
          <span className="episode-card__cta">Read →</span>
        </div>
      </div>
    </div>
  );
}
