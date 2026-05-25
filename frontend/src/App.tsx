import { useEffect, useRef, useState } from 'react';
import { api } from './api/client';
import { ChatPanel } from './components/ChatPanel';
import { EpisodePicker } from './components/EpisodePicker';
import { Flipbook } from './components/Flipbook';
import type { Episode } from './api/types';

// Two views, switched by a single piece of state. Post 7 adds the chat panel
// beside the reader: picking an episode opens a server-side reading session,
// and every page flip PATCHes the session's current_page — which is what the
// spoiler-safe retrieval layer filters on.
export function App() {
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [orientation, setOrientation] = useState<'portrait' | 'landscape'>('landscape');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const pagePatchTimer = useRef<number | null>(null);

  // Open (or clear) a reading session when the selected episode changes.
  useEffect(() => {
    if (!selectedEpisode) {
      setSessionId(null);
      return;
    }
    let cancelled = false;
    setSessionId(null);
    api
      .createSession(selectedEpisode.slug)
      .then((res) => {
        if (!cancelled) setSessionId(res.session_id);
      })
      .catch((err) => console.warn('createSession failed:', err));
    return () => {
      cancelled = true;
    };
  }, [selectedEpisode]);

  // Push the reader's position to the server, debounced — flipping fires this
  // rapidly, and only the page they land on needs to be recorded.
  useEffect(() => {
    if (!sessionId) return;
    if (pagePatchTimer.current !== null) window.clearTimeout(pagePatchTimer.current);
    pagePatchTimer.current = window.setTimeout(() => {
      api.updateCurrentPage(sessionId, currentPage).catch((err) =>
        console.warn('updateCurrentPage failed:', err),
      );
    }, 300);
    return () => {
      if (pagePatchTimer.current !== null) window.clearTimeout(pagePatchTimer.current);
    };
  }, [sessionId, currentPage]);

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
        <ChatPanel sessionId={sessionId} currentPage={currentPage} isSpread={showSpread} />
      </main>
    </div>
  );
}
