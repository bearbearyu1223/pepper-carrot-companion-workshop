import { useEffect, useRef, useState } from 'react';
import { streamMessage } from '../api/client';
import type { ChatMessage, Mode, Suggestion } from '../api/types';

// Inline so the workshop doesn't pull in an icon library. Page = open book,
// wiki = stacked books — matching the two chip colors.
function ModeIcon({ mode }: { mode: Mode }) {
  if (mode === 'page') {
    return (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 5c-1.5-1-4-1.5-6-1.5S2.5 4 2 4.5v14c.5-.5 2.5-1 4-1s4.5.5 6 1.5c1.5-1 4-1.5 6-1.5s3.5.5 4 1v-14c-.5-.5-2.5-1-4-1s-4.5.5-6 1.5Z"
          stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M12 5v14" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    );
  }
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 4h3v16H5zM10 4h3v16h-3z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="m16 5 3 .6-2.6 14-3-.6z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

function SuggestionChips({
  suggestions,
  onPick,
  disabled,
}: {
  suggestions: Suggestion[];
  onPick: (s: Suggestion) => void;
  disabled: boolean;
}) {
  if (suggestions.length === 0) return null;
  return (
    <div className="suggestion-chips" role="group" aria-label="Suggested follow-ups">
      {suggestions.map((s, i) => (
        <button
          key={`${s.mode}:${i}`}
          type="button"
          className={`suggestion-chip suggestion-chip--${s.mode}`}
          onClick={() => onPick(s)}
          disabled={disabled}
          title={s.mode === 'page' ? 'Asks about the current page' : 'Asks the wiki'}
        >
          <ModeIcon mode={s.mode} />
          <span>{s.text}</span>
        </button>
      ))}
    </div>
  );
}

interface ChatPanelProps {
  sessionId: string | null;
  currentPage: number;
  isSpread: boolean;
}

export function ChatPanel({ sessionId, currentPage, isSpread }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  // New episode → new session → fresh conversation.
  useEffect(() => {
    setMessages([]);
  }, [sessionId]);

  // Keep the newest message in view as tokens stream in.
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages]);

  const sendMessage = async (text: string, mode: Mode) => {
    if (!sessionId || !text.trim() || streaming) return;

    // Optimistically append the user bubble + an empty assistant bubble we'll
    // fill token by token (matched by id).
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', content: text, mode },
      { id: assistantId, role: 'assistant', content: '', mode },
    ]);
    setDraft('');
    setStreaming(true);

    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));

    try {
      for await (const event of streamMessage(sessionId, { mode, message: text, spread: isSpread })) {
        if (event.type === 'token') {
          patch((m) => ({ ...m, content: m.content + event.text }));
        } else if (event.type === 'done') {
          patch((m) => ({ ...m, suggestions: event.suggestions }));
        } else if (event.type === 'error') {
          patch((m) => ({
            ...m,
            content: m.content || `The companion hit a snag (${event.code}). Try again.`,
          }));
        }
      }
    } catch {
      patch((m) => ({ ...m, content: m.content || 'The connection dropped — try again.' }));
    } finally {
      setStreaming(false);
    }
  };

  if (!sessionId) {
    return <aside className="chat-panel chat-panel--idle">Starting a reading session…</aside>;
  }

  const hint = isSpread
    ? `Reading pages ${currentPage}–${currentPage + 1}`
    : `Reading page ${currentPage}`;

  return (
    <aside className="chat-panel">
      <div className="chat-hint">{hint}</div>

      <div className="chat-log" ref={logRef}>
        {messages.length === 0 && (
          <p className="chat-empty">
            Ask about what&rsquo;s on the page — or switch to the wiki for lore about Hereva.
            The companion only knows the pages you&rsquo;ve already read.
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`chat-msg chat-msg--${m.role}`}>
            <div className="chat-bubble">
              {m.content || (streaming ? '…' : '')}
            </div>
            {m.role === 'assistant' && m.suggestions && (
              <SuggestionChips
                suggestions={m.suggestions}
                onPick={(s) => void sendMessage(s.text, s.mode)}
                disabled={streaming}
              />
            )}
          </div>
        ))}
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          void sendMessage(draft, 'page');
        }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about this page…"
          disabled={streaming}
          aria-label="Ask a question about the current page"
        />
        <div className="chat-actions">
          <button type="submit" className="chat-send" disabled={streaming || !draft.trim()}>
            Send
          </button>
          <button
            type="button"
            className="chat-wiki"
            disabled={streaming || !draft.trim()}
            onClick={() => void sendMessage(draft, 'wiki')}
          >
            Ask the wiki
          </button>
        </div>
      </form>
    </aside>
  );
}
