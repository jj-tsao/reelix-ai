"""FastMCP server definition and stdio serving.

Tool handlers live   in ``reelix_mcp.tools`` as transport-agnostic functions;
this module only binds them to MCP tool schemas and runs the stdio transport
against the protocol stream preserved by ``stdio_guard``.
"""

from __future__ import annotations

import io
from typing import Annotated, Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server
from pydantic import Field

from reelix_mcp.runtime import AppContext
from reelix_mcp.tools.recommend import run_recommend
from reelix_mcp.tools.why import run_why

# Canonical vocabularies, mirroring the orchestrator tool schema
# (reelix_agent/tools/recommendation_tool.py). Deliberately not enforced as
# enums yet: unknown values pass through and simply don't match filters.
GENRES = (
    "Action, Comedy, Drama, Romance, Science Fiction, Thriller, Adventure, "
    "Animation, Crime, Documentary, Family, Fantasy, History, Horror, Music, "
    "Mystery, War, Western"
)
PROVIDERS = (
    "Netflix, Hulu, HBO Max, Disney+, Apple TV+, Amazon Prime Video, "
    "Paramount+, Peacock Premium, MGM+, Starz, AMC+, Crunchyroll, BritBox, "
    "Acorn TV, Criterion Channel, Tubi TV, Pluto TV, The Roku Channel"
)

INSTRUCTIONS = """\
Reelix movie recommendations, powered by a hybrid retrieval pipeline
(dense + BM25 via Qdrant) with an LLM curator that scores every candidate on
genre/tone/theme fit. Two-phase flow: recommend_media returns the curated
slate fast; get_why_explanations redeems the returned query_id for per-title
rationales. Pass the returned session_id into follow-up calls to refine
(already-seen titles are penalized).
"""


def build_mcp_server(ctx: AppContext) -> FastMCP:
    mcp = FastMCP("reelix", instructions=INSTRUCTIONS)

    @mcp.tool(
        name="recommend_media",
        description=(
            "Get a curated slate of movie recommendations for a taste query. "
            "Recommendation-only: translate the user's intent into the spec "
            "fields yourself (this tool does no query planning). Returns "
            "ranked picks plus a query_id redeemable via get_why_explanations."
        ),
    )
    async def recommend_media(
        query_text: Annotated[
            str,
            Field(
                description=(
                    "Compact retrieval-oriented description of what to watch, "
                    "e.g. 'slow-burn neo-noir with a melancholy streak'. "
                    "Exclude meta-instructions like 'on Netflix' or 'from the "
                    "90s' — express those via providers/year_range."
                )
            ),
        ],
        media_type: Annotated[
            Literal["movie"],
            Field(description="Type of media to recommend. Use 'movie'."),
        ] = "movie",
        core_genres: Annotated[
            list[str] | None,
            Field(description=f"Canonical genre names to prioritize: {GENRES}."),
        ] = None,
        exclude_genres: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Genres to EXCLUDE (only for explicit negative preferences "
                    f"like 'no horror'): {GENRES}."
                )
            ),
        ] = None,
        sub_genres: Annotated[
            list[str] | None,
            Field(
                description=(
                    "More specific sub-genre descriptors, e.g. 'psychological "
                    "thriller', 'romantic comedy'."
                )
            ),
        ] = None,
        core_tone: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Tone/vibe adjectives for how it should feel emotionally, "
                    "e.g. 'melancholic', 'feel-good', 'tense'."
                )
            ),
        ] = None,
        key_themes: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Thematic ideas or subject-matter concerns, e.g. 'grief', "
                    "'found family', 'corporate greed'."
                )
            ),
        ] = None,
        providers: Annotated[
            list[str] | None,
            Field(
                description=(
                    f"Streaming services to filter to: {PROVIDERS}. "
                    "Omit for no provider filter."
                )
            ),
        ] = None,
        year_range: Annotated[
            list[int] | None,
            Field(
                description=(
                    "Release-year range as [start_year, end_year] (inclusive), "
                    "e.g. [1990, 1999]. Omit when unconstrained."
                )
            ),
        ] = None,
        session_id: Annotated[
            str | None,
            Field(
                description=(
                    "Pass back the session_id from a previous result to refine "
                    "it (follow-up turns penalize already-recommended titles). "
                    "Omit to start fresh."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        return await run_recommend(
            ctx,
            query_text=query_text,
            media_type=media_type,
            core_genres=core_genres,
            exclude_genres=exclude_genres,
            sub_genres=sub_genres,
            core_tone=core_tone,
            key_themes=key_themes,
            providers=providers,
            year_range=year_range,
            session_id=session_id,
        )

    @mcp.tool(
        name="get_why_explanations",
        description=(
            "Redeem a query_id from recommend_media for per-title 'why you'll "
            "enjoy it' rationales. Blocking; idempotent; valid ~15 minutes "
            "after the recommendation call."
        ),
    )
    async def get_why_explanations(
        query_id: Annotated[
            str,
            Field(description="query_id returned by a recent recommend_media call."),
        ],
    ) -> dict[str, Any]:
        return await run_why(ctx, query_id=query_id)

    return mcp


async def serve(server: FastMCP, protocol_stdout: io.TextIOWrapper) -> None:
    """Run the stdio transport against the preserved protocol stream.

    Equivalent to ``FastMCP.run_stdio_async`` except the write side is the
    descriptor saved by ``stdio_guard.install()`` — ``sys.stdout`` points at
    stderr by the time this runs.
    """
    async with stdio_server(stdout=anyio.wrap_file(protocol_stdout)) as (read, write):
        await server._mcp_server.run(
            read,
            write,
            server._mcp_server.create_initialization_options(),
        )
