# Reelix MCP Server

Exposes the Reelix recommendation pipeline as [MCP](https://modelcontextprotocol.io)
tools over stdio, so any MCP client (Claude Desktop, Claude Code, …) can pull
curated movie recommendations from the same retrieval → curation → explanation
stack that powers the web app. FastAPI and MCP are two transports over the
shared `reelix_runtime` bootstrap — no pipeline logic lives here.

## Tools

| Tool | What it does |
|------|--------------|
| `recommend_media` | Structured taste spec in (the calling agent does the query planning) → hybrid retrieval → LLM curator → ranked slate + `query_id` + `session_id`. Pass `session_id` back to refine (seen titles are penalized). |
| `get_why_explanations` | Redeems a `query_id` (Redis ticket, idempotent, ~15 min TTL) for per-title "why you'll enjoy it" rationales as one blocking payload. |

v1 runs anonymous (`user_id="mcp-anon"`) — no per-user taste vectors.

## Setup

```bash
cd apps/mcp-server
uv sync
cp .env.example .env   # fill in credentials (same as apps/api)
```

First run downloads the embedding model from Hugging Face; warm it once so the
MCP client's first spawn doesn't hit the download:

```bash
uv run python -c "from reelix_models.custom_models import load_sentence_model; load_sentence_model()"
```

## Register with a client

Claude Code:

```bash
claude mcp add reelix -- uv --directory /path/to/Reelix/apps/mcp-server run python -m reelix_mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "reelix": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/Reelix/apps/mcp-server",
        "run", "python", "-m", "reelix_mcp"
      ]
    }
  }
}
```

Credentials come from `apps/mcp-server/.env`, so the client config stays
secret-free.

## Development

```bash
uv run ruff check .
uv run pytest              # integration test auto-skips without credentials
npx @modelcontextprotocol/inspector uv --directory . run python -m reelix_mcp
```

### Notes

- **stdout discipline**: MCP owns stdout. `reelix_mcp/stdio_guard.py` re-points
  fd 1 at stderr at process start and hands the real pipe to the MCP transport,
  so stray `print()`s in shared packages can't corrupt the protocol.
- **Telemetry**: identical Supabase rows as web traffic, distinguished by
  `endpoint='mcp/explore'`, `request_meta->>'transport'='mcp-stdio'`, and
  `user_id='mcp-anon'`. Each tool call opens a root OTel span
  (`mcp.recommend_media` / `mcp.get_why_explanations`, service `reelix-mcp`);
  the explanation trace links back to its recommend trace via the ticket.
- **Memory**: each spawned server is a full torch + sentence-transformers
  process (several GB RSS). Fine for local use; a shared Streamable HTTP
  deployment mounted on the FastAPI app is the planned v2.
