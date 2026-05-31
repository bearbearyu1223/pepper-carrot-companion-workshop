// Typed API client for the backend.
//
// Plain fetch + Promises for the read endpoints (Post 5) and the session
// lifecycle (Post 6). The chat stream (Post 7) is a hand-parsed Server-Sent
// Events reader: the request is a POST with a JSON body, so the browser's
// built-in `EventSource` (GET-only) can't be used — we read the response body
// as a stream and parse the SSE frames ourselves.

import type {
  Episode,
  EpisodeDetail,
  Mode,
  Session,
  Suggestion,
  WorldGraph,
  WorldGraphMode,
} from './types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listEpisodes: () => get<{ episodes: Episode[] }>('/api/episodes'),
  getEpisode: (slug: string) => get<EpisodeDetail>(`/api/episodes/${slug}`),

  // Start a reading session for an episode (opens at page 1).
  createSession: async (episodeSlug: string): Promise<Session> => {
    const res = await fetch(`${BASE_URL}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ episode_slug: episodeSlug }),
    });
    if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
    return res.json() as Promise<Session>;
  },

  // Tell the server the reader has flipped to a new page. This is the only way
  // the spoiler boundary moves — it's debounced by the caller on every flip.
  updateCurrentPage: async (sessionId: string, currentPage: number): Promise<void> => {
    const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_page: currentPage }),
    });
    if (!res.ok) throw new Error(`updateCurrentPage failed: ${res.status}`);
  },

  // Spoiler-filtered snapshot of the world graph for the reader's current
  // position. The cursor lives in the URL — the API clamps it to the
  // episode's real page count and the filter is a SQL row-value compare,
  // not a prompt instruction (Post 9). `mode='focus'` returns on-page
  // characters + 1-hop neighbors; `mode='full'` returns the whole spoiler-
  // safe world. `rightPage` is the right page of a two-page spread (so the
  // landscape reader's focus seed unions both visible pages).
  fetchWorldGraph: (
    episodeSlug: string,
    page: number,
    mode: WorldGraphMode = 'full',
    rightPage?: number,
  ): Promise<WorldGraph> => {
    const params = new URLSearchParams({
      episode_slug: episodeSlug,
      page: String(page),
      mode,
    });
    if (rightPage !== undefined && rightPage !== page) {
      params.set('right_page', String(rightPage));
    }
    return get<WorldGraph>(`/api/world-graph?${params.toString()}`);
  },
};

// The events `streamMessage` yields. `done` carries the suggestion chips.
export type ChatStreamEvent =
  | { type: 'token'; text: string }
  | { type: 'done'; messageId: string; retrievedDocIds: string[]; suggestions: Suggestion[] }
  | { type: 'error'; code: string; message: string };

// POST a question and yield events as the answer streams in.
//
// SSE frames are separated by blank lines; within a frame, `event:` names the
// event and `data:` carries a JSON payload. Comment lines (starting with `:`)
// are the server's keep-alive heartbeat and are skipped.
export async function* streamMessage(
  sessionId: string,
  body: { mode: Mode; message: string; spread?: boolean },
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  });
  if (!res.body) {
    yield { type: 'error', code: 'no_body', message: 'No response body' };
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    // sse-starlette emits CRLF; normalize so the blank-line split works.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');

    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? ''; // keep the trailing partial frame

    for (const frame of frames) {
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (!line || line.startsWith(':')) continue; // blank or heartbeat
        if (line.startsWith('event:')) event = line.slice(6).trimStart();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
      }
      if (dataLines.length === 0) continue;

      try {
        const parsed = JSON.parse(dataLines.join('\n'));
        if (event === 'token') {
          yield { type: 'token', text: parsed.text };
        } else if (event === 'done') {
          yield {
            type: 'done',
            messageId: parsed.message_id,
            retrievedDocIds: parsed.retrieved_doc_ids ?? [],
            suggestions: parsed.suggestions ?? [],
          };
        } else if (event === 'error') {
          yield { type: 'error', code: parsed.code, message: parsed.message };
        }
      } catch {
        // Ignore an unparseable frame rather than killing the whole stream.
      }
    }
  }
}
