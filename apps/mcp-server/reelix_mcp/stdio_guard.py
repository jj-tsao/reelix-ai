"""Protect the MCP stdio protocol stream from stray stdout writes.

MCP over stdio owns fd 1: any non-protocol byte (a ``print()`` in a shared
package, a C-level write from torch/tokenizers) corrupts the JSON-RPC stream
and kills the session. Rather than chasing every write site, swap the file
descriptors once at process start: fd 1 is re-pointed at stderr, and the real
protocol pipe is preserved on a private descriptor handed to the MCP server.

Must be installed before ANY heavy import (see ``__main__``). Stdlib-only.
"""

from __future__ import annotations

import io
import os
import sys


def install() -> io.TextIOWrapper:
    """Reserve the real stdout for the MCP protocol; route everything else to stderr.

    After this call fd 1 *is* stderr, so any later write to stdout — Python or
    native — lands in the client's log pane instead of the protocol stream.

    Returns a text stream over the preserved original stdout, to be passed to
    ``mcp.server.stdio.stdio_server(stdout=anyio.wrap_file(...))``.
    """
    protocol_fd = os.dup(1)  # keep the pipe the MCP client is reading
    os.dup2(2, 1)  # fd 1 now points at stderr
    # Rebind sys.stdout onto the redirected fd 1 with timely flushing so
    # buffered print() output appears promptly in the client's MCP logs.
    sys.stdout = os.fdopen(1, "w", buffering=1, closefd=False)

    raw = os.fdopen(protocol_fd, "wb", buffering=0)
    return io.TextIOWrapper(raw, encoding="utf-8", newline="\n", write_through=True)
