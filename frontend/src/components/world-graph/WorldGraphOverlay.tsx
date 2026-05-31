// Slide-in side panel that hosts the WorldGraph. Right-anchored on
// desktop, full-screen sheet on mobile. The backdrop dims the flipbook
// without hiding it, so the reader keeps a sense of where they are.
// Esc and backdrop click both dismiss.

import { useEffect } from 'react';
import { WorldGraph } from './WorldGraph';

interface WorldGraphOverlayProps {
  episodeSlug: string;
  page: number;
  onAskInWiki: (entityName: string) => void;
  onClose: () => void;
}

export function WorldGraphOverlay({
  episodeSlug,
  page,
  onAskInWiki,
  onClose,
}: WorldGraphOverlayProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // The InfoCard's keydown listener uses capture + stopPropagation,
      // so an open card swallows Esc before it reaches us. Esc here
      // only fires when no card is open.
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="world-overlay" role="dialog" aria-label="World graph">
      <div
        className="world-overlay__backdrop"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className="world-overlay__panel">
        <header className="world-overlay__header">
          <h2>🌐 World</h2>
          <button
            type="button"
            className="world-overlay__close"
            onClick={onClose}
            aria-label="Close world view"
          >
            ×
          </button>
        </header>
        <WorldGraph
          episodeSlug={episodeSlug}
          page={page}
          onAskInWiki={onAskInWiki}
        />
      </aside>
    </div>
  );
}
