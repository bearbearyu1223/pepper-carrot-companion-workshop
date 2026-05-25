// Shared TypeScript types matching the backend API surface.
//
// These types are the wire-format contract with the FastAPI backend. Keep
// them in sync with the Pydantic response models in
// `backend/app/api/episodes.py`. (A later iteration can swap this file for
// generated types via `openapi-typescript`; for two endpoints the cost of
// a generator is greater than the cost of keeping ~30 lines in sync.)

export interface ImageMetadata {
  width?: number;
  height?: number;
  blurhash?: string;
  dominant_color?: string;
}

export interface Character {
  id: string;
  name: string;
  image_url?: string | null;
}

export interface Page {
  id: string;
  page_number: number;
  image_url: string;
  thumbnail_url: string | null;
  image_metadata: ImageMetadata;
  characters: Character[];
}

export interface Episode {
  id: string;
  slug: string;
  title: string;
  episode_number: number;
  cover_image_url: string | null;
  page_count: number;
  // Full plot summary — generated at ingestion time by the chat client
  // (see ingestion/ingest.py). null only when the episode hasn't been
  // ingested yet.
  plot_summary: string | null;
}

export interface EpisodeDetail extends Episode {
  credits_url: string | null;
  characters: Character[];
  pages: Page[];
}

// ─── Chat (Post 7) ──────────────────────────────────────────────────────────

// The two question pipelines. The user picks per message via the UI; the model
// never decides. Mirrors `Mode` in backend/app/retrieval/service.py.
export type Mode = 'page' | 'wiki';

// One follow-up chip rendered below an assistant reply. Clicking it sends the
// text as the next question, routed through the chip's own `mode`.
export interface Suggestion {
  mode: Mode;
  text: string;
}

// A chat bubble in the panel's local state (not a wire type — the backend
// persists its own chat_messages rows).
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  mode?: Mode;
  suggestions?: Suggestion[];
}

// Response from POST /api/sessions.
export interface Session {
  session_id: string;
  current_page: number;
}
