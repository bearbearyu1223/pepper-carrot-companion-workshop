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
