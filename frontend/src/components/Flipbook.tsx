import { useEffect, useRef, useState } from 'react';
import { PageFlip } from 'page-flip';
import { api } from '../api/client';
import type { Episode, EpisodeDetail } from '../api/types';

interface FlipbookProps {
  episode: Episode;
  onPageChange: (pageNumber: number) => void;
  // Fires on init and whenever PageFlip switches between portrait (single page)
  // and landscape (two-page spread). Lets the parent phrase the page indicator
  // correctly ("Pages N–N+1" when both pages are visible) and — in later posts
  // — lets the chat panel say "Reading pages N–N+1 of M".
  onOrientationChange?: (mode: 'portrait' | 'landscape') => void;
}

export function Flipbook({ episode, onPageChange, onOrientationChange }: FlipbookProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const flipRef = useRef<PageFlip | null>(null);
  const onPageChangeRef = useRef(onPageChange);
  const onOrientationChangeRef = useRef(onOrientationChange);
  const [detail, setDetail] = useState<EpisodeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  // Keep the latest callback in a ref so the PageFlip effect doesn't re-run on
  // identity changes — only when the episode itself changes.
  useEffect(() => {
    onPageChangeRef.current = onPageChange;
  }, [onPageChange]);
  useEffect(() => {
    onOrientationChangeRef.current = onOrientationChange;
  }, [onOrientationChange]);

  useEffect(() => {
    setDetail(null);
    setError(null);
    setCurrentPage(1);
    api
      .getEpisode(episode.slug)
      .then(setDetail)
      .catch((err) => setError(String(err)));
  }, [episode.slug]);

  useEffect(() => {
    if (!detail || !containerRef.current) return;
    const wrapper = containerRef.current;

    // Wipe anything React doesn't own before mounting a fresh PageFlip.
    // Without this, React StrictMode's dev-only setup → cleanup → setup
    // cycle (and any path where PageFlip's destroy chain doesn't fully
    // remove its block) leaves a stale flipbook inside the wrapper, and
    // the second flipbook renders OVER it — which presents as duplicate
    // pages briefly visible mid-flip, and an apparent "page moves up"
    // artifact when the static leftover stays below the active flipbook.
    while (wrapper.firstChild) wrapper.removeChild(wrapper.firstChild);

    // PageFlip takes over the element it's given (and removes it on destroy()),
    // so give it an inner element React doesn't own.
    const flipRoot = document.createElement('div');
    flipRoot.className = 'flipbook';
    wrapper.appendChild(flipRoot);

    const pageEls: HTMLElement[] = detail.pages.map((page) => {
      const el = document.createElement('div');
      el.className = 'page';
      el.dataset.pageNumber = String(page.page_number);
      const img = document.createElement('img');
      img.src = page.image_url;
      img.alt = `Page ${page.page_number}`;
      img.draggable = false;
      el.appendChild(img);
      flipRoot.appendChild(el);
      return el;
    });

    const flip = new PageFlip(flipRoot, {
      width: 600,
      height: 847, // matches the 2481×3503 source aspect (~1.412).
      size: 'stretch',
      minWidth: 280,
      maxWidth: 1200,
      minHeight: 395,
      maxHeight: 1700,
      maxShadowOpacity: 0.5,
      showCover: false,
      useMouseEvents: true,
      drawShadow: true,
      usePortrait: true,
      mobileScrollSupport: true,
      flippingTime: 700,
    });
    flip.loadFromHTML(pageEls);

    // Single source of truth for the visible page: read getCurrentPageIndex()
    // directly. The `flip` event's `e.data` payload is the index PageFlip
    // just stored internally, which can briefly diverge from what's actually
    // drawn — most reliably on the single-page spread that an odd-page-count
    // episode produces in landscape (e.g. page 3 alone in a 3-page episode),
    // and on landscape↔portrait transitions that rebuild the spread layout.
    // Querying getCurrentPageIndex() inside each handler sidesteps the drift.
    const reportPage = () => {
      const pageNumber = flip.getCurrentPageIndex() + 1;
      setCurrentPage(pageNumber);
      onPageChangeRef.current(pageNumber);
    };

    flip.on('flip', reportPage);
    flip.on('init', reportPage);
    flip.on('changeOrientation', (e) => {
      const mode = (e as { data: 'portrait' | 'landscape' }).data;
      onOrientationChangeRef.current?.(mode);
      // Orientation switches rebuild the spread layout; the leftmost visible
      // page can shift without a `flip` event. Re-sync explicitly.
      reportPage();
    });

    // Emit initial orientation immediately so the parent's pill label is
    // correct before any user gesture (PageFlip's own `init` event fires
    // on the next tick, which is too late for the first render).
    onOrientationChangeRef.current?.(flip.getOrientation());
    flipRef.current = flip;

    return () => {
      flip.destroy(); // removes flipRoot from wrapper; React's wrapper stays.
      flipRef.current = null;
    };
  }, [detail]);

  // Preload current ± 2 pages so the next flip has the image ready.
  useEffect(() => {
    if (!detail) return;
    const targets = detail.pages.filter(
      (p) => Math.abs(p.page_number - currentPage) <= 2 && p.page_number !== currentPage
    );
    const links = targets.map((page) => {
      const link = document.createElement('link');
      link.rel = 'preload';
      link.as = 'image';
      link.href = page.image_url;
      document.head.appendChild(link);
      return link;
    });
    return () => {
      links.forEach((l) => l.remove());
    };
  }, [detail, currentPage]);

  if (error) return <div className="error">Failed to load episode: {error}</div>;
  if (!detail) return <div className="loading">Loading episode…</div>;

  return <div ref={containerRef} className="flipbook-wrapper" />;
}
