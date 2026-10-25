BEGIN;
INSERT INTO episodes (id, slug, title, episode_number, language)
  VALUES (gen_random_uuid(), 'ep01-potion-of-flight', 'Episode 1: The Potion of Flight', 1, 'en');
INSERT INTO chat_sessions (id, episode_id, current_page)
  SELECT gen_random_uuid(), e.id, 1 FROM episodes e, generate_series(1, 1000);
INSERT INTO chat_messages (id, session_id, role, content, retrieved_doc_ids, token_counts, created_at)
  SELECT gen_random_uuid(), s.id, 'user', 'hello', '[]', '{}', now() - g * interval '1 minute'
  FROM chat_sessions s, generate_series(1, 100) g;
ANALYZE chat_messages;
SELECT id AS sid FROM chat_sessions LIMIT 1 \gset
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
  SELECT * FROM chat_messages WHERE session_id = :'sid' ORDER BY created_at;
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
  SELECT * FROM chat_messages WHERE session_id = :'sid' ORDER BY created_at DESC LIMIT 20;
DROP INDEX ix_chat_messages_session_created;
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
  SELECT * FROM chat_messages WHERE session_id = :'sid' ORDER BY created_at;
ROLLBACK;
