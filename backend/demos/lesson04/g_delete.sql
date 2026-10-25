SELECT id AS ep FROM episodes WHERE episode_number = 6 \gset
SELECT conrelid::regclass AS child, confrelid::regclass AS parent,
  CASE confdeltype WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL' END AS on_delete
  FROM pg_constraint WHERE contype = 'f' ORDER BY parent, child;
BEGIN;
CREATE TEMP VIEW counts AS SELECT
  (SELECT count(*) FROM pages) AS pages,
  (SELECT count(*) FROM page_characters) AS page_characters,
  (SELECT count(*) FROM chat_sessions) AS chat_sessions,
  (SELECT count(*) FROM chat_messages) AS chat_messages,
  (SELECT count(*) FROM characters) AS characters;
TABLE counts;
DELETE FROM episodes WHERE id = :'ep';
TABLE counts;
ROLLBACK;
