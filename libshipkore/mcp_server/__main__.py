import argparse
import logging
import os
import sys

from libshipkore.common.exceptions import ConfigError, ShipkoreError

from .config import load_config

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TOKEN_ENV = "LIBSHIPKORE_MCP_TOKEN"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="libshipkore-mcp",
        description="MCP server for libshipkore (shipping tools for AI agents).",
    )
    parser.add_argument(
        "--config",
        help="JSON config file (providers, credentials, storage, files). "
             "Defaults to $LIBSHIPKORE_CONFIG; with neither, the server runs with "
             "in-memory storage and no credentials.",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="stdio (default) is started by the client; http serves streamable HTTP "
             "on the local machine only.",
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"http only: a loopback address or localhost (default {DEFAULT_HOST}). "
             "Anything else is refused.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"http only: port to listen on (default {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--no-auth", action="store_true",
        help="http only: do not require a bearer token. Any user or process on this "
             "machine can then use the tools with this server's credentials.",
    )
    parser.add_argument(
        "--no-elicit", action="store_true",
        help="Do not ask the user directly to approve a write when the client "
             "supports it; the preview-and-token step still applies.",
    )
    parser.add_argument(
        "--confirm-ttl", type=int, default=600, metavar="SECONDS",
        help="How long a confirmation token stays valid (default 600).",
    )
    return parser.parse_args(argv)


def announce_http(host, port, token, generated, no_auth):
    url = f"http://{host if ':' not in host else '[' + host + ']'}:{port}/mcp"
    log = logging.getLogger("libshipkore.mcp")
    log.info("libshipkore-mcp listening on %s", url)
    if no_auth:
        log.warning(
            "authentication is OFF: any user or process on this machine can use "
            "these tools with this server's credentials")
    elif generated:
        log.info("generated a one-time token; clients must send:  Authorization: Bearer %s", token)
        log.info("to keep one across restarts, set %s", TOKEN_ENV)
    else:
        log.info("clients must send  Authorization: Bearer $%s", TOKEN_ENV)


def main(argv=None):
    args = parse_args(argv)
    # stdout carries the protocol in stdio mode, so logs always go to stderr
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        from .server import build_server
    except ImportError as error:
        sys.exit(
            f"libshipkore-mcp needs the MCP SDK ({error}). "
            "Install it with: pip install 'libshipkore[mcp]'"
        )
    from . import http
    token = generated = None
    try:
        if args.transport == "http":
            http.require_loopback(args.host)
            if not 1 <= args.port <= 65535:
                raise ConfigError(f"--port must be between 1 and 65535, got {args.port}")
            token, generated = http.resolve_token(os.environ, no_auth=args.no_auth)
        elif args.no_auth or args.host != DEFAULT_HOST or args.port != DEFAULT_PORT:
            logging.getLogger("libshipkore.mcp").warning(
                "--host, --port and --no-auth only apply to --transport http")
        from libshipkore.client import Shipkore
        kore = Shipkore.from_config(load_config(args.config))
        server = build_server(
            kore, close_kore=args.transport == "stdio",
            elicit=not args.no_elicit, confirm_ttl=args.confirm_ttl,
        )
    except (ConfigError, ShipkoreError) as error:
        sys.exit(f"libshipkore-mcp: {error}")
    if args.transport == "stdio":
        server.run()
        return
    announce_http(args.host, args.port, token, generated, args.no_auth)
    try:
        http.serve(server, args.host, args.port, token)
    finally:
        kore.close()


if __name__ == "__main__":
    main()
