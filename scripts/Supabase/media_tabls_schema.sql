-- == TMDB ↔ IMDb ID mapping ==
create table if not exists media_ids (
  tmdb_id   bigint primary key,
  imdb_id   text unique    -- e.g. 'tt0068646'; unique to avoid duplicate mappings
);

create index if not exists idx_media_ids_imdb_id
  on media_ids(imdb_id);


-- == Ratings, votes, award info from external sources ==
create table if not exists media_ratings (
  tmdb_id         bigint primary key,
  imdb_id         text,

  -- IMDb data
  imdb_rating     numeric(3,1),   -- e.g. 9.2
  imdb_votes      integer,        -- e.g. 2182094

  -- Rotten Tomatoes
  rt_score        numeric(5,2),   -- treat as 0–100; 5,2 gives flexibility

  rt_last_checked timestamptz,    -- when the score was last queried
  rt_status       text,           -- 'ok' | 'not_found' | 'error' | null

  -- Extra signals
  metascore       integer.    ,   -- Metacritic 0–100
  awards_summary  text,           -- e.g. 'Won 3 Oscars. 31 wins & 31 nominations total'

  updated_at      timestamptz default now()
);

-- FK to keep ratings aligned with known titles
alter table media_ratings
  add constraint media_ratings_tmdb_fk
  foreign key (tmdb_id) references media_ids (tmdb_id)
  on delete cascade;

-- Indexes for common lookups / joins
create index if not exists idx_media_ratings_imdb_id
  on media_ratings(imdb_id);

create index if not exists idx_media_ratings_updated_at
  on media_ratings(updated_at);

-- Optional: if you ever filter by status a lot (e.g. 'ok' vs 'not_found')
create index if not exists idx_media_ratings_rt_status
  on media_ratings(rt_status);


-- == Raw IMDb ratings sync table (direct mirror of title.ratings.tsv.gz) ==
create table if not exists imdb_ratings_raw (
  tconst         text primary key,  -- IMDb title ID, e.g. 'tt0068646'
  averageRating  numeric(3,1),      -- e.g. 9.2
  numVotes       integer            -- e.g. 2182094
);

-- General performance indexes
create index if not exists idx_imdb_ratings_num_votes
  on imdb_ratings_raw(numVotes);

create index if not exists idx_imdb_ratings_avg_rating
  on imdb_ratings_raw(averageRating);
