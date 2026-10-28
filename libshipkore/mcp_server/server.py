import contextlib

from mcp.server import MCPServer

from libshipkore import __version__
from libshipkore.client import Shipkore

from .tools import register_read_tools, register_resources

INSTRUCTIONS = """\
libshipkore: shipping for Indian and global carriers.

Start with list_providers: it shows which providers exist, which operations each
supports, and which have credentials configured on this server. Tracking works
for every provider without credentials.

Rules:
- Credentials live in the server's configuration. Never ask the user to paste
  API keys or passwords into the chat.
- Check check_serviceability (and get_rates) before proposing a booking.
- Dates are ISO 8601. Money is in the provider's currency, usually INR.
- A tool error explains what to change; read it before retrying.
"""


def build_server(kore=None, close_kore=None):
    """
    The MCP server. With no `kore` it builds one from the environment
    (LIBSHIPKORE_STORAGE, LIBSHIPKORE_FILES) and closes it on shutdown; a
    `kore` passed in is left open unless close_kore is true.
    """
    owns = kore is None if close_kore is None else close_kore
    kore = kore or Shipkore()

    @contextlib.asynccontextmanager
    async def lifespan(server):
        try:
            yield {"kore": kore}
        finally:
            if owns:
                kore.close()

    mcp = MCPServer(
        "libshipkore",
        title="libshipkore shipping",
        instructions=INSTRUCTIONS,
        version=__version__,
        lifespan=lifespan,
    )
    register_read_tools(mcp, kore)
    register_resources(mcp, kore)
    return mcp
