import argparse
import logging
import sys

from libshipkore.common.exceptions import ConfigError, ShipkoreError

from .config import load_config


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
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    # stdout carries the protocol, so everything human-readable goes to stderr
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    try:
        from .server import build_server
    except ImportError as error:
        sys.exit(
            f"libshipkore-mcp needs the MCP SDK ({error}). "
            "Install it with: pip install 'libshipkore[mcp]'"
        )
    try:
        from libshipkore.client import Shipkore
        server = build_server(Shipkore.from_config(load_config(args.config)),
                              close_kore=True)
    except (ConfigError, ShipkoreError) as error:
        sys.exit(f"libshipkore-mcp: {error}")
    server.run()


if __name__ == "__main__":
    main()
