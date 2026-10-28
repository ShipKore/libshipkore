import contextlib

from mcp.server import MCPServer

from libshipkore import __version__
from libshipkore.client import Shipkore

from .confirm import DEFAULT_TTL, PendingActions
from .tools import register_read_tools, register_resources, register_write_tools

INSTRUCTIONS = """\
libshipkore: shipping for Indian and global carriers.

Start with list_providers: it shows which providers exist, which operations each
supports, and which have credentials configured on this server. Tracking works
for every provider without credentials.

Rules:
- Credentials live in the server's configuration. Never ask the user to paste
  API keys or passwords into the chat.
- Check check_serviceability (and get_rates) before proposing a booking.
- create_order, cancel_order, schedule_pickup and ndr_action change things at a
  provider, so each takes two calls. The first, without confirmation_token,
  changes nothing and returns a preview with a token. Show the preview, with its
  warnings, to the user and wait for approval. Then repeat the call with exactly
  the same arguments plus the token. Never invent a user's approval.
- shipkore://capability-matrix says what each provider's API supports and how sure
  we are of it; read it when unsure whether a provider can do something.
- Dates are ISO 8601. Money is in the provider's currency, usually INR.
- A tool error explains what to change; read it before retrying.
"""


def build_server(kore=None, close_kore=None, elicit=True, confirm_ttl=DEFAULT_TTL,
                 pending=None):
    """
    The MCP server. With no `kore` it builds one from the environment
    (LIBSHIPKORE_STORAGE, LIBSHIPKORE_FILES) and closes it on shutdown; a
    `kore` passed in is left open unless close_kore is true.

    Tools that change something at a provider take two calls (preview, then
    confirm with a token valid for `confirm_ttl` seconds). With `elicit`, the
    user is also asked directly when the client supports it.
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
    pending = pending or PendingActions(kore.storage, ttl=confirm_ttl)
    register_read_tools(mcp, kore)
    register_write_tools(mcp, kore, pending, elicit=elicit)
    register_resources(mcp, kore)
    return mcp
