import { useState } from 'react';
import { EpisodePicker } from './components/EpisodePicker';
import { Flipbook } from './components/Flipbook';
import type { Episode } from './api/types';

// Two views, switched by a single piece of state. No router yet — the chat
// panel and world graph in later posts will need URL state (deep links to a
// specific page, in particular), at which point react-router-dom or a
// hash-based scheme gets added. For now, picker ↔ reader is enough.
export function App() {
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(1);
  // 'landscape' = two-page spread visible; 'portrait' = single page. Drives
  // the page-indicator phrasing ("Pages N–N+1" vs "Page N") and — in later
  // posts — the chat panel's context hint.
  const [orientation, setOrientation] = useState<'portrait' | 'landscape'>('landscape');

  if (!selectedEpisode) {
    return <EpisodePicker onSelect={setSelectedEpisode} />;
  }

  const totalPages = selectedEpisode.page_count;
  const rightPage = Math.min(currentPage + 1, totalPages);
  const showSpread = orientation === 'landscape' && rightPage > currentPage;
  const pageLabel = showSpread
    ? `Pages ${currentPage}–${rightPage} of ${totalPages}`
    : `Page ${currentPage} of ${totalPages}`;

  return (
    <div className="app-layout">
      <header className="app-header">
        <button className="header-back" onClick={() => setSelectedEpisode(null)}>
          ← Episodes
        </button>
        <h1>{selectedEpisode.title}</h1>
        <span className="header-page-indicator" aria-live="polite">
          {pageLabel}
        </span>
        <span className="attribution">
          By{' '}
          <a href="https://www.peppercarrot.com" target="_blank" rel="noreferrer">
            David Revoy
          </a>
          {' · '}
          <a
            href="https://creativecommons.org/licenses/by/4.0/"
            target="_blank"
            rel="noreferrer"
          >
            CC BY 4.0
          </a>
        </span>
      </header>
      <main className="app-main">
        <Flipbook
          episode={selectedEpisode}
          onPageChange={setCurrentPage}
          onOrientationChange={setOrientation}
        />
      </main>
    </div>
  );
}
