"""Entry point — install the patch, then hand off to reddit-no-auth-mcp-server."""
from __future__ import annotations

import logging
import sys

from . import __version__
from .patch import install as install_patch


def main() -> int:
    """Run the MCP server with Chrome cookies + curl_cffi TLS impersonation.

    Installs the per-adapter patch, then calls `reddit-no-auth-mcp-server`'s
    entry point. Exits with the upstream server's exit code.
    """
    logging.basicConfig(level=logging.WARNING)
    install_patch()

    print(
        f"[reddit-mcp-chrome v{__version__}] Patched redd adapters — "
        f"using Chrome cookies + Chrome TLS impersonation",
        file=sys.stderr,
    )

    # Hand off to the upstream MCP server's CLI main.
    from reddit_mcp_server.adapters.inbound.mcp_cli_adapter import main as upstream_main
    return upstream_main()


if __name__ == "__main__":
    sys.exit(main())
