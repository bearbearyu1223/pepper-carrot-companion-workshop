SELECT id AS ep FROM episodes WHERE episode_number = 6 \gset
SELECT episode_number, slug, title, published_at::date FROM episodes WHERE id = :'ep';
SELECT page_number, mood_tags FROM pages WHERE episode_id = :'ep' ORDER BY page_number;
SELECT id AS p4 FROM pages WHERE episode_id = :'ep' AND page_number = 4 \gset
\x on
SELECT page_number, image_url, left(visual_description, 69) || '…' AS visual_description
  FROM pages WHERE id = :'p4';
\x off
SELECT c.name, c.aliases
  FROM page_characters pc JOIN characters c ON c.id = pc.character_id
  WHERE pc.page_id = :'p4' ORDER BY c.name;
SELECT c.name, array_agg(p.page_number ORDER BY p.page_number) AS pages
  FROM pages p
  JOIN page_characters pc ON pc.page_id = p.id
  JOIN characters c ON c.id = pc.character_id
  WHERE p.episode_id = :'ep' AND c.name IN ('Pepper', 'Saffron')
  GROUP BY c.name;
