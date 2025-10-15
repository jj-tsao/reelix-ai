-- Core query log (/discovery & /recommendations)
create table if not exists rec_queries (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  endpoint text not null check (endpoint in ('discovery/for-you','recommendations/interactive')),
  query_id text not null,
  user_id uuid,
  session_id text not null,
  media_type text not null,
  query_text text,
  pipeline_version text,
  batch_size int not null,
  request_meta jsonb
);

create index if not exists idx_rec_queries_endpoint_time on rec_queries (endpoint, created_at desc);
create index if not exists idx_rec_queries_qid on rec_queries (query_id);

-- Candidates (/discovery & /recommendations)
create table if not exists rec_results (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  endpoint text not null check (endpoint in ('discovery/for-you','recommendations/interactive')),
  query_id text not null,
  media_type text not null,
  media_id text not null,
  rank int not null,
  title text,
  score_final double precision,
  score_dense double precision,
  score_sparse double precision,
  meta_breakdown jsonb,
  source_meta jsonb
);
create index if not exists idx_rec_results_ep_qid_rank on rec_results (endpoint, query_id, rank);

-- Discovery streaming lifecycle (SSE)
create table if not exists discovery_stream_events (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  query_id text not null,
  batch_id int,
  event text not null,                    -- 'started' | 'why_delta' | 'done' | 'error'
  media_id text,
  chunk_count int,                        -- increments for a media_id
  bytes_total int,
  duration_ms int,                        -- duration for this batch or aggregate at 'done'
  error_message text
);
create index if not exists idx_discovery_stream_events_query_id on discovery_stream_events (query_id);

-- Recommendations/interactive final recs
create table if not exists rec_llm_selections (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  query_id text not null references rec_queries(query_id) on delete cascade,
  model text not null,                   -- e.g., gpt-4o-mini
  params jsonb,                          -- temperature, top_p, seed, etc.
  prompt_hash text,                      -- hash of messages/prompt
  latency_ms int,
  input_tokens int,
  output_tokens int,
  selected_ids text[] not null,          -- final ~5 in order
  audit jsonb                            -- optional: per-id selection_score/reason snippet
);
create index if not exists idx_llm_sel_qid on rec_llm_selections (query_id);
