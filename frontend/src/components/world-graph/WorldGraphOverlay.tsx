// Slide-in side panel that hosts the WorldGraph. Right-anchored on
// desktop, full-screen sheet on mobile. The backdrop dims the flipbook
// without hiding it, so the reader keeps a sense of where they are.
// Esc and backdrop click both dismiss.

import { useEffect } from 'react';
import { WorldGraph } from './WorldGraph';

interface WorldGraphOverlayProps {
  episodeSlug: string;
  page: number;
  // Right page of the spread when the flipbook is in landscape mode;
  // pass the same as `page` (or omit) for single-page mode. Focus mode
  // uses [page, rightPage] as the seeding range.
  rightPage?: number;
  onAskInWiki: (entityName: string) => void;
  onClose: () => void;
}

export function WorldGraphOverlay({
  episodeSlug,
  page,
  rightPage,
  onAskInWiki,
  onClose,
}: WorldGraphOverlayProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // The InfoCard's keydown listener uses capture phase +
      // stopPropagation, so an open card swallows Esc before it
      // reaches us. Esc only closes the overlay when no card is open.
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
          <div className="world-overlay__title">
            {/* Hand-inked tendril: a thin curve with a leaf-tip and a
                small bud. Sits before the title to nudge the panel away
                from CMS chrome and toward "page from a witch's
                journal". Stroke uses currentColor so it inherits the
                title's color. */}
            <svg
              className="world-overlay__flourish"
              viewBox="0 0 36 18"
              width="36"
              height="18"
              role="presentation"
              aria-hidden="true"
            >
              <path
                d="M2 9 C 6 4, 10 4, 14 9 S 22 14, 26 9"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
              <path
                d="M26 9 q 3 -3 7 -2"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
              <circle cx="33" cy="7" r="1.6" fill="currentColor" />
            </svg>
            <h2>World</h2>
          </div>
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
          rightPage={rightPage}
          onAskInWiki={onAskInWiki}
        />
      </aside>
    </div>
  );
}
