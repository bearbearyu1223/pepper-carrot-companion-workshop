SELECT id AS ep FROM episodes WHERE episode_number = 6 \gset
SELECT id AS p4 FROM pages WHERE episode_id = :'ep' AND page_number = 4 \gset
BEGIN;
INSERT INTO chat_sessions (id, episode_id, current_page)
  VALUES (gen_random_uuid(), :'ep', 3) RETURNING id AS sid \gset
UPDATE chat_sessions SET current_page = 4 WHERE id = :'sid' RETURNING current_page;
INSERT INTO chat_messages
  (id, session_id, role, content, retrieved_doc_ids, token_counts)
  VALUES (gen_random_uuid(), :'sid', 'user', 'Who are these four witches?', '[]', '{}');
INSERT INTO chat_messages
  (id, session_id, role, mode, content, retrieved_doc_ids, token_counts)
  VALUES (gen_random_uuid(), :'sid', 'assistant', 'page',
    'The four contestants: Coriander, Saffron, Shichimi and Pepper.',
    jsonb_build_array(:'p4'), '{}');
SELECT m.role, m.mode, p.page_number AS retrieved_page
  FROM chat_messages m LEFT JOIN pages p ON m.retrieved_doc_ids ? p.id::text
  WHERE m.session_id = :'sid' ORDER BY m.role DESC;
ROLLBACK;
