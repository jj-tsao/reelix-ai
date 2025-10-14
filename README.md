# 🎬 Reelix AI – Personalized Movie & TV Show Discovery

[![Netlify](https://img.shields.io/badge/Live%20Site-Netlify-42b883?logo=netlify)](https://reelixai.netlify.app/)
[![Retriever Model](https://img.shields.io/badge/Retriever%20Model-HuggingFace-blue?logo=huggingface)](https://huggingface.co/JJTsao/fine-tuned_movie_retriever-bge-base-en-v1.5)
[![Intent Classifier](https://img.shields.io/badge/Intent%20Classifier-HuggingFace-blue?logo=huggingface)](https://huggingface.co/JJTsao/intent-classifier-distilbert-moviebot)
[![CE Reranker](https://img.shields.io/badge/CE%20Reranker-HuggingFace-blue?logo=huggingface)]([https://huggingface.co/JJTsao/intent-classifier-distilbert-moviebot](https://huggingface.co/JJTsao/movietv-reranker-cross-encoder-base-v1))
[![Made with FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi)](https://jjtsao-rag-movie-api.hf.space/docs#/)
[![Built with React](https://img.shields.io/badge/Frontend-React-61dafb?logo=react)](https://reelixai.netlify.app/)
![License](https://img.shields.io/github/license/jj-tsao/rag-movie-recommender-app)

**Reelix** is an AI-native discovery agent that understands *vibes* and turns them into cinematic picks. It blends hybrid retrieval (dense + BM25), metadata scoring, and a fine-tuned Cross-Encoder reranker before handing the final slate to an LLM for concise, spoiler-light “Why you’ll like it” reasons—streamed live to the UI.

---

## 🌐 Live Product
👉 Try it here: [**Reelix AI**](https://reelixai.netlify.app/)

---

## 🔥 What’s New

### 1) Taste Onboarding (`/taste`)
Create a personal taste vector from your likes/dislikes and genre/vibe signals. The service builds and stores a dense taste profile, with endpoints to **inspect** and **rebuild** your profile:
1) `POST /taste_profile/rebuild`
   Rebuilds from interactions and persists to Supabase
3) `GET /taste_profile/me`
   Returns last build metadata & vector dim

Under the hood, the rebuild process fetches user signals, loads item embeddings from Qdrant, and calls `build_taste_vector(...)`, then upserts the profile.

### 2) For-You Feed (`/discover`)
Your **For-You** page streams personalized reasons (and markdown rich movie/tv profile) per item in real-time. The flow is a two-step ticketed orchestration:

1) `POST /discovery/for-you`  
   Returns the candidate list plus a `stream_url` for reasons.

2) `GET /discovery/for-you/why?query_id=...` (SSE)  
   Streams events `{started, why_delta, done}` where `why_delta` includes `media_id`, optional `imdb_rating` and `rotten_tomatoes_rating`, and `why_you_might_enjoy_it` markdown.

The endpoint uses a **ticket store** (memory or Redis) with idle and absolute TTLs to hold LLM prompts and guard access by user id.

### 3) Vibe Query (`/query`)
Explore by vibe with free-form natural language and optional filters (providers, genres, release years, media type). The request → stream flow mirrors the For-You feed:

1) `POST /recommendations/interactive`
- Runs the interactive recipe (dense + BM25 + metadata + CE reranker) to fetch ~20 top candidates.
- Builds an LLM prompt with those candidates and user taste context if signed in.
- Streams the final recommendations and their “why” write-ups as the response body (text stream).

This flow uses the same ticket store (memory or Redis) with idle and absolute TTLs to hold LLM prompts and guard access by user id.


### **Frontend details**
- `/discover` loads a grid of picks, then begins SSE streaming of “why” and ratings, updating each card live.
- Users can **Love / Like / Not for me** or **watch trailer**; feedback is logged and triggers controlled taste rebuilds.
- **Smart rebuild controller**: after any rating, start/refresh a 10s timer; if ≥2 ratings when the timer fires, rebuild—**max 1 rebuild per 2 minutes**; queue one pending rebuild during cooldown.



---

## 🏗️ Architecture (High-Level)

```
Taste signals → Taste Vector ──┐
                               │
User query ──▶ Dense+BM25 ──► Candidate Pool (RRF#1) ─► Metadata Rerank ─► CE Rerank ─► Final Fusion (RRF#2) ─► LLM "Why"
                                   ▲                                                             │
                                   │                                                             ▼
                               Filters (providers/genres/year)                           SSE stream to UI
```

- **Bootstrap & Lifespan**: loads intent classifier, embedder, BM25, CE reranker, Qdrant client, and configures ticket store.
- **Orchestrator**: Recipes (`interactive`, `for_you_feed`) define inputs (query vs taste), retrieval params, and LLM prompt envelopes.


---

## ✨ Features

- **Hybrid Retrieval + Double Fusion**
  - Dense (fine-tuned `bge-base-en-v1.5`) and sparse BM25 retrieval
  - Weighted **metadata rerank** (semantic, sparse, quality, popularity, optional genre)
  - **Cross-Encoder reranker** (BERT) with GPU-friendly batching/lengths
  - RRF fusion for stable final ordering (pre-pool & final)

- **For-You Weights (taste-aware)**  
  `dense=0.56, sparse=0.13, rating=0.15, popularity=0.04, genre=0.12`

- **Interactive Query Weights (vibe query)**  
  `dense=0.60, sparse=0.10, rating=0.18, popularity=0.12, genre=0.00`

- **LLM Reasoning (streamed)**  
  Server streams JSONL “why” payloads per item via SSE; UI renders markdown and ratings incrementally.

- **Front-End UX**  
  - `/query` page: rotating vibe placeholders, media-type tabs, collapsible advanced filters, streaming card grid.
  - `/discover` page: wide cards, live reason/rating deltas, built-in feedback & trailer actions.


---

## 📚 API Endpoints (Key)

### Taste Profile
- `GET /taste_profile/me` → profile meta (last build time, pos/neg counts, dim)
- `POST /taste_profile/rebuild` → rebuilds from interactions and stores profile

### Discovery (For-You)
- `POST /discovery/for-you` → `{ query_id, items[], stream_url }`
- `GET /discovery/for-you/why?query_id=...` (SSE) → events: `started`, many `why_delta`, `done`

### Query (Interactive)
- Your `/query` page posts a vibe description + filters; back end runs **interactive recipe** (query-conditioned) and streams markdown cards.

---
## 🚀 Tech Stack

| Layer        | Tech                     |
|-------------|--------------------------|
| Frontend               | React + Vite + Tailwind CSS + ShadCN UI              |
| Backend                | FastAPI (Python) + Docker                            |
| Embedding/ Retrieval   | SentenceTransformers (fine-tuned `bge-base-en-v1.5`) + BM25 |
| Reranking              | **Cross‑Encoder (fine-tuned `bert-base-uncased`)** + Metadata + **RRF** |
| Intent Classification  | DistilBERT (fine-tuned `distilbert-base-uncased`)    |
| Sparse Search          | BM25 (Best Match 25) via `rank_bm25`                 |
| Tokenization           | NLTK (Natural Language Toolkit)                      |
| Vector DB              | Qdrant (hybrid search)                               |
| Storage                | Supabase (profiles, interactions, logs)              |
| Ticket Store           | In-memory or Redis (gzip)                            |
| Chat Completion        | OpenAI API (streamed JSONL/SSE)                      |
| Movie Metadata         | TMDB (The Movie Database) API                        |
| Model Hosting          | Hugging Face Hub                                     |
| Deployment             | Frontend: Netlify, Backend: Hugging Face Spaces      |

---

## 🧪 Example Prompts

- “Slow-burn thrillers with morally complex characters and rich atmosphere”
- “Visually stunning sci-fi with existential undertones”
- “Playful rom-coms with quirky characters and heartfelt moments”

---

## 📈 Metrics

**Sentence Transformer Retriever Model:**

| Metric     | Fine-Tuned `bge-base-en-v1.5` | Base `bge-base-en-v1.5` |
| ---------- | :---------------------------: | :---------------------: |
| Recall\@1  |           **0.456**           |          0.214          |
| Recall\@3  |           **0.693**           |          0.361          |
| Recall\@5  |           **0.758**           |          0.422          |
| Recall\@10 |           **0.836**           |          0.500          |
| MRR        |           **0.595**           |          0.315          |

**Model Details**: [JJTsao/fine-tuned_movie_retriever-bge-base-en-v1.5](https://huggingface.co/JJTsao/fine-tuned_movie_retriever-bge-base-en-v1.5)

<br />

**Alternative Light-Weight Model:**
  
| Metric      | Fine-Tuned `all-minilm-l6-v2` | Base `all-minilm-l6-v2` |
|-------------|:-----------------------------:|:-----------------------:|
| Recall@1    |           **0.428**           |          0.149          |
| Recall@3    |           **0.657**           |          0.258          |
| Recall@5    |           **0.720**           |          0.309          |
| Recall@10   |           **0.795**           |          0.382          |
| MRR         |           **0.563**           |          0.230          |

**Model Details**: [JJTsao/fine-tuned_movie_retriever-all-minilm-l6-v2](https://huggingface.co/JJTsao/fine-tuned_movie_retriever-all-minilm-l6-v2)

<br />

**Evaluation setup**:
- Dataset: 3,598 held-out metadata and vibe-style natural queries
- Method: Top-k ranking using cosine similarity between query and positive documents
- Goal: Assess top-k retrieval quality in recommendation-like settings

---

## 🛠️ Development

### Backend
```bash
# Env
export QDRANT_ENDPOINT=...
export QDRANT_API_KEY=...
export SUPABASE_URL=...
export SUPABASE_API_KEY=...
export OPENAI_API_KEY=...

# Run
uvicorn main:app --reload --port 7860
```

### Frontend
```bash
npm install
npm run dev
# build: npm run build
```

---

## 📝 License
MIT
