"""
Preview-then-confirm for the tools that change something at a provider.

A write tool called without a confirmation token does nothing but validate
and describe: it returns a Preview and a token. The same call repeated with
that token and identical arguments performs the action. A token is

- bound to the exact arguments of the preview (a SHA-256 of them), so the
  action cannot drift between what was shown and what runs;
- single use: claiming it is one atomic delete, so two simultaneous
  confirmations cannot both win, even across processes sharing a database;
- short lived, 10 minutes by default; and
- stored only as a hash.

What this is not: proof that a person approved. An agent can call twice in a
row. It forces a checkpoint and stops accidental one-shot writes. Real
approval comes from the client asking the user before it runs a tool, and,
where the client supports it, from the direct question asked here.
"""
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python

from libshipkore.common.exceptions import ConfirmationError
from libshipkore.common.models import Model

from .errors import run_blocking

logger = logging.getLogger("libshipkore.mcp")

COLLECTION = "pending_actions"
DEFAULT_TTL = 600


class Preview(Model):
    """What a write tool returns the first time: nothing has been changed."""

    status: Literal["preview"] = "preview"
    action: str
    headline: str
    summary: dict[str, Any]
    warnings: list[str] = []
    confirmation_token: str
    expires_at: str
    next_step: str


@dataclass
class Described:
    """What a write tool says it is about to do."""

    headline: str
    summary: dict
    warnings: list = field(default_factory=list)


def canonical(arguments):
    """The arguments as stable JSON, whatever mix of models, enums and dates they hold."""
    return json.dumps(
        to_jsonable_python(arguments), sort_keys=True, separators=(",", ":")
    )


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class PendingActions:
    def __init__(self, storage, ttl=DEFAULT_TTL, now=None):
        self.storage = storage
        self.ttl = ttl
        self._now = now or (lambda: datetime.now(timezone.utc))

    def issue(self, action, arguments, described):
        self._purge_expired()
        token = secrets.token_urlsafe(24)
        expires = self._now() + timedelta(seconds=self.ttl)
        self.storage.put(COLLECTION, _digest(token), {
            "key": _digest(token),
            "action": action,
            "arguments_hash": _digest(canonical(arguments)),
            "headline": described.headline,
            "summary": to_jsonable_python(described.summary),
            "created_at": self._now().isoformat(),
            "expires_at": expires.isoformat(),
        })
        return Preview(
            action=action,
            headline=described.headline,
            summary=to_jsonable_python(described.summary),
            warnings=described.warnings,
            confirmation_token=token,
            expires_at=expires.isoformat(),
            next_step=(
                "Nothing has been changed. Show this preview, including the warnings, "
                "to the user and wait for their approval. Then call "
                f"{action} again with exactly the same arguments plus "
                f"confirmation_token. The token is single use and expires at "
                f"{expires.isoformat()}."
            ),
        )

    def check(self, token, action, arguments):
        """The stored preview if this token may run these arguments now; else ConfirmationError."""
        redo = f"Call {action} again without a token to get a new preview."
        document = self.storage.get(COLLECTION, _digest(token))
        if document is None:
            raise ConfirmationError(
                f"That confirmation token is unknown, already used or expired. {redo}"
            )
        if datetime.fromisoformat(document["expires_at"]) <= self._now():
            self.storage.delete(COLLECTION, _digest(token))
            raise ConfirmationError(f"That confirmation token has expired. {redo}")
        if document["action"] != action:
            raise ConfirmationError(
                f"That token was issued for {document['action']}, not {action}. {redo}"
            )
        if document["arguments_hash"] != _digest(canonical(arguments)):
            raise ConfirmationError(
                "These arguments differ from the preview the token was issued for. "
                "Either repeat the previewed arguments exactly, or get a new "
                f"preview. {redo}"
            )
        return document

    def claim(self, token):
        """Use the token up. Exactly one caller gets True."""
        return self.storage.delete(COLLECTION, _digest(token))

    def discard(self, token):
        self.storage.delete(COLLECTION, _digest(token))

    def _purge_expired(self):
        now = self._now()
        for document in self.storage.list(COLLECTION):
            if datetime.fromisoformat(document["expires_at"]) <= now:
                self.storage.delete(COLLECTION, document["key"])


class _Approve(BaseModel):
    approve: bool = Field(description="Approve this action?")


async def ask_user(ctx, headline):
    """
    Ask the person directly through the client. True if they accept, False if
    they decline or dismiss, None if the client cannot be asked (no support, or
    a connection type that disallows server-initiated questions).
    """
    try:
        result = await ctx.elicit(message=headline, schema=_Approve)
    except Exception as error:
        logger.debug("cannot ask the user directly: %r", error)
        return None
    if result.action == "accept":
        return bool(result.data.approve)
    return False


async def two_step(ctx, pending, *, action, arguments, token, describe, execute,
                   elicit=True):
    """
    The whole protocol for one write tool. `describe` and `execute` are
    blocking callables; `describe` must not change anything.
    """
    if token is None:
        described = await run_blocking(describe)
        return await run_blocking(pending.issue, action, arguments, described)
    document = await run_blocking(pending.check, token, action, arguments)
    if elicit and ctx is not None:
        decision = await ask_user(ctx, document["headline"])
        if decision is False:
            await run_blocking(pending.discard, token)
            raise ToolError(
                "The user declined this action, so nothing was changed. "
                "Ask what they would like instead."
            )
    if not await run_blocking(pending.claim, token):
        raise ToolError(
            "That confirmation token was just used by another call, so this one "
            f"did nothing. Check with get_order before retrying {action}."
        )
    return await run_blocking(execute)
