"""
Turn library errors into messages an agent can act on.

The SDK shows the model only the message of a ToolError. Any other
exception reaches it as a bare "Error executing tool" and is logged as a
crash, which is right for real bugs but wrong for the failures below, so
each expected failure is converted here with a next step in it.
"""
import functools

import anyio
import requests
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from libshipkore.common.exceptions import (
    ConfigError,
    CredentialsError,
    DuplicateOrder,
    NotFound,
    ProviderError,
    ShipkoreError,
    StorageError,
    UnknownProvider,
    UnsupportedOperation,
)
from libshipkore.provider import list_providers

MAX_BODY = 300


def _capabilities(slug):
    try:
        return list_providers().get(slug)
    except Exception:
        return None


def _unknown_provider(error):
    # the error already carries "Did you mean ...?" when a name is close
    return ToolError(f"{str(error).rstrip('.')}. Call list_providers to see every provider.")


def _unsupported(error):
    text = str(error)
    slug = text.partition(": ")[0]
    supported = _capabilities(slug)
    if supported is None:
        return ToolError(f"Not supported: {text}.")
    return ToolError(
        f"Not supported: {text}. {slug} supports: {', '.join(supported)}. "
        "Call list_providers to compare providers."
    )


def _provider_error(error):
    parts = [str(error)]
    if error.status_code:
        parts.append(f"(HTTP {error.status_code})")
    if error.body:
        body = str(error.body).strip().replace("\n", " ")
        parts.append("Provider said: " + body[:MAX_BODY] + ("..." if len(body) > MAX_BODY else ""))
    parts.append("The provider rejected the call; fix the arguments or see get_recorded_responses.")
    return ToolError(" ".join(parts))


def translate(error):
    """A ToolError for an expected failure, or None to let the SDK treat it as a crash."""
    if isinstance(error, ToolError):
        return error
    if isinstance(error, UnknownProvider):
        return _unknown_provider(error)
    if isinstance(error, UnsupportedOperation):
        return _unsupported(error)
    if isinstance(error, CredentialsError):
        return ToolError(
            f"{error}. Add it under providers.<name>.credentials in the server's config "
            "file (or reference an environment variable as ${NAME}). Do not ask the user "
            "to paste secrets into the chat."
        )
    if isinstance(error, DuplicateOrder):
        return ToolError(f"{error}. Use get_order to see it, or choose a different order id.")
    if isinstance(error, NotFound):
        return ToolError(str(error))
    if isinstance(error, ProviderError):
        return _provider_error(error)
    if isinstance(error, (StorageError, ConfigError)):
        return ToolError(
            f"Server configuration problem: {error}. This needs the server's operator, "
            "not a different tool call."
        )
    if isinstance(error, ValidationError):
        fields = ", ".join(sorted({".".join(map(str, e["loc"])) or "input" for e in error.errors()}))
        return ToolError(f"Invalid values for: {fields}. {error.errors()[0]['msg']}")
    if isinstance(error, ValueError):
        return ToolError(str(error))
    if isinstance(error, ShipkoreError):
        return ToolError(str(error))
    return None


async def run_blocking(function, *args, scraper=False, **kwargs):
    """
    Run a blocking library call in a worker thread and convert its expected
    failures. scraper=True also treats network errors and parse failures of
    a tracker, whose pages and APIs change without notice, as expected.
    """
    try:
        return await anyio.to_thread.run_sync(functools.partial(function, *args, **kwargs))
    except Exception as error:
        converted = translate(error)
        if converted is None and scraper:
            if isinstance(error, requests.RequestException):
                converted = ToolError(
                    f"Could not reach the provider: {type(error).__name__}. "
                    "Try again shortly."
                )
            else:
                converted = ToolError(
                    f"The provider's tracking page or API returned something unexpected "
                    f"({type(error).__name__}); it may have changed. "
                    "Check the waybill, or try another provider."
                )
        if converted is None:
            raise
        raise converted from error
