"""
The local HTTP transport.

It is local on purpose. Three layers keep it that way:

1. It only binds to a loopback address (require_loopback), so it is not
   reachable from other machines. Remote use needs real authentication and
   per-user credentials, which this server does not have.
2. The SDK's Host and Origin checks (TransportSecuritySettings) stop a web
   page in the user's browser reaching it through DNS rebinding.
3. A bearer token (BearerToken) stops other users and processes on the same
   machine, who can reach 127.0.0.1 too, from driving the tools with this
   server's credentials. A token is required unless --no-auth says otherwise.
"""
import hmac
import ipaddress
import logging
import secrets

from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from libshipkore.common.exceptions import ConfigError

logger = logging.getLogger("libshipkore.mcp")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PATH = "/mcp"
TOKEN_ENV = "LIBSHIPKORE_MCP_TOKEN"
MIN_TOKEN_LENGTH = 16


def require_loopback(host):
    """Return host if it is a loopback address or localhost; otherwise refuse."""
    candidate = (host or "").strip()
    if candidate.lower() == "localhost":
        return candidate
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        address = None
    # an IPv4-mapped address such as ::ffff:192.168.1.1 is only loopback if its IPv4 part is
    mapped = getattr(address, "ipv4_mapped", None)
    if address is not None and (mapped or address).is_loopback:
        return candidate
    raise ConfigError(
        f"refusing to listen on '{host}': the HTTP transport is local-only (use "
        "127.0.0.1, ::1 or localhost). It has no per-user authentication, so it "
        "must not be reachable from other machines. Use the stdio transport, or "
        "put your own authenticated proxy in front."
    )


def resolve_token(environ, no_auth=False, env_name=TOKEN_ENV):
    """
    The bearer token to require, and whether it was generated. From the
    environment when set (and long enough), else a fresh random one. None
    only when auth was explicitly switched off.
    """
    if no_auth:
        return None, False
    supplied = environ.get(env_name, "")
    if supplied:
        if len(supplied) < MIN_TOKEN_LENGTH:
            raise ConfigError(
                f"{env_name} is too short: use at least {MIN_TOKEN_LENGTH} characters "
                "(for example the output of `openssl rand -hex 24`)"
            )
        return supplied, False
    return secrets.token_urlsafe(32), True


def security_settings(port):
    """Accept only requests addressed to this server on a loopback name, from no foreign origin."""
    names = ("127.0.0.1", "localhost", "[::1]")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{name}:{port}" for name in names],
        allowed_origins=[f"http://{name}:{port}" for name in names],
    )


class BearerToken:
    """ASGI middleware: every HTTP request must carry `Authorization: Bearer <token>`."""

    def __init__(self, app, token):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not self._allowed(Headers(scope=scope)):
            response = JSONResponse(
                {"error": "unauthorized"}, status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _allowed(self, headers):
        scheme, _, supplied = headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(
            supplied.strip().encode(), self.token
        )


def build_app(server, port, token=None, path=PATH):
    """The ASGI application: the SDK's streamable HTTP app behind the guards above."""
    app = server.streamable_http_app(
        streamable_http_path=path,
        transport_security=security_settings(port),
        host=DEFAULT_HOST,
    )
    return BearerToken(app, token) if token else app


def serve(server, host, port, token=None):
    import uvicorn

    uvicorn.Server(uvicorn.Config(
        build_app(server, port, token), host=host, port=port, log_level="info",
    )).run()
