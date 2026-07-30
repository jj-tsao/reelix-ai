"""Entry point: ``python -m reelix_mcp``.

Order matters here: the stdio guard must own fd 1 before any heavy import —
 and a single stray stdout byte corrupts the MCP protocol stream.
"""

import logging
import sys
from pathlib import Path

from reelix_mcp import stdio_guard  # stdlib-only import, safe before the guard

_protocol_stdout = stdio_guard.install()

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("reelix_mcp")


def main() -> None:
    # Anchor .env to the app directory: MCP clients spawn this process with an
    # arbitrary cwd, so a relative lookup would silently find nothing.
    from dotenv import load_dotenv  # noqa: PLC0415

    app_dir = Path(__file__).resolve().parents[1]
    load_dotenv(app_dir / ".env", override=False)

    # Tracing first so spans from bootstrap-time clients attach correctly.
    from reelix_runtime.telemetry.tracing import init_tracing_core  # noqa: PLC0415

    init_tracing_core(default_service_name="reelix-mcp")

    # Heavy: loads embedding model + BM25 assets, connects Qdrant/Redis.
    import anyio  # noqa: PLC0415

    from reelix_mcp.runtime import AppContext  # noqa: PLC0415
    from reelix_mcp.server import build_mcp_server, serve  # noqa: PLC0415
    from reelix_mcp.settings import McpSettings  # noqa: PLC0415

    ctx = AppContext.build(McpSettings())
    server = build_mcp_server(ctx)
    log.info("Reelix MCP server ready — serving on stdio")

    async def _run() -> None:
        try:
            await serve(server, _protocol_stdout)
        finally:
            await ctx.aclose()

    anyio.run(_run)


if __name__ == "__main__":
    main()
