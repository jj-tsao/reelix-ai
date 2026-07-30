"""End-to-end integration test over real stdio.

Spawns the server exactly as an MCP client would and drives it with the SDK's
stdio client. The client transport fails on any non-protocol stdout byte, so
this doubles as the stdout-purity assertion under real load.

Skipped unless credentials are present (needs Qdrant/Redis/OpenAI/Supabase).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]

_REQUIRED_ENV = (
    "QDRANT_ENDPOINT",
    "QDRANT_API_KEY",
    "OPENAI_API_KEY",
    "REDIS_URL",
    "SUPABASE_URL",
    "SUPABASE_API_KEY",
)


def _has_creds() -> bool:
    if all(os.getenv(k) for k in _REQUIRED_ENV):
        return True
    env_file = APP_DIR / ".env"
    if not env_file.exists():
        return False
    contents = env_file.read_text()
    return all(
        any(
            line.startswith(f"{key}=") and line.split("=", 1)[1].strip()
            for line in contents.splitlines()
        )
        for key in _REQUIRED_ENV
    )


pytestmark = pytest.mark.skipif(
    not _has_creds(), reason="requires Qdrant/Redis/OpenAI/Supabase credentials"
)


def _payload(result) -> dict:
    """Extract the JSON payload from a CallToolResult."""
    assert not result.isError, result.content
    if result.structuredContent:
        # FastMCP wraps non-BaseModel returns under "result"
        return result.structuredContent.get("result", result.structuredContent)
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_stdio_round_trip():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command="uv",
        args=["--directory", str(APP_DIR), "run", "python", "-m", "reelix_mcp"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {"recommend_media", "get_why_explanations"}

            recs = _payload(
                await session.call_tool(
                    "recommend_media",
                    {
                        "query_text": "tense heist thriller with a clever crew",
                        "core_genres": ["Thriller", "Crime"],
                    },
                )
            )
            assert recs["query_id"] and recs["session_id"]
            assert recs["items"], "expected a non-empty slate"
            first = recs["items"][0]
            assert first["title"] and first["media_id"]
            assert "poster_url" not in first and "backdrop_url" not in first
            assert recs["why"]["available"] is True

            why = _payload(
                await session.call_tool(
                    "get_why_explanations", {"query_id": recs["query_id"]}
                )
            )
            assert why["count"] == len(why["explanations"]) > 0
            assert all(e["why"] for e in why["explanations"])

            # Ticket is idempotent: a second redemption also succeeds.
            again = _payload(
                await session.call_tool(
                    "get_why_explanations", {"query_id": recs["query_id"]}
                )
            )
            assert again["count"] > 0

            # Unknown query_id surfaces a friendly error, not a crash.
            bad = await session.call_tool(
                "get_why_explanations", {"query_id": "nonexistent"}
            )
            assert bad.isError


@pytest.fixture
def anyio_backend():
    return "asyncio"
