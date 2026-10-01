CREATE TABLE IF NOT EXISTS short_links (
  slug TEXT PRIMARY KEY,
  target_url TEXT NOT NULL,
  owner_token TEXT NOT NULL
);
