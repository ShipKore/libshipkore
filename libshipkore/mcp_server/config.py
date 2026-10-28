import json
import logging
import os
import re
import stat

from libshipkore.common.exceptions import ConfigError

logger = logging.getLogger("libshipkore.mcp")

ENV_VAR = "LIBSHIPKORE_CONFIG"

# the only keys Shipkore accepts from a config file; anything else is a typo
ALLOWED_KEYS = {
    "providers", "storage", "files", "sandbox", "track_ttl",
    "label_url_expiry", "record_responses",
}
PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value, where, environ):
    """Replace ${NAME} with the environment variable, so secrets can stay out of the file."""
    if isinstance(value, str):
        def lookup(match):
            name = match.group(1)
            if name not in environ:
                raise ConfigError(
                    f"{where} refers to ${{{name}}} but that environment variable is not set"
                )
            return environ[name]
        return PLACEHOLDER.sub(lookup, value)
    if isinstance(value, dict):
        return {k: _expand(v, f"{where}.{k}", environ) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, f"{where}[{i}]", environ) for i, v in enumerate(value)]
    return value


def _holds_literal_secret(value):
    """True when a credentials block contains a value that is not an ${ENV} reference."""
    return isinstance(value, dict) and any(
        isinstance(v, str) and v and not PLACEHOLDER.fullmatch(v) for v in value.values()
    )


def load_config(path=None, environ=None):
    """
    The keyword arguments for `Shipkore`, read from a JSON file at `path` or
    $LIBSHIPKORE_CONFIG. With neither, returns {} and the server runs with
    in-memory storage and no credentials, which is enough to track.

        {
          "providers": {
            "delhivery": {"credentials": {"api_token": "${DELHIVERY_TOKEN}"},
                          "sandbox": true}
          },
          "storage": "sqlite:////var/lib/shipkore/kore.db",
          "files": "s3://my-bucket/labels"
        }
    """
    environ = os.environ if environ is None else environ
    path = path or environ.get(ENV_VAR)
    if not path:
        return {}
    try:
        with open(path) as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read config file {path}: {error}")
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    unknown = sorted(set(raw) - ALLOWED_KEYS)
    if unknown:
        raise ConfigError(
            f"unknown config keys {unknown} in {path}; allowed: {sorted(ALLOWED_KEYS)}"
        )
    providers = raw.get("providers", {})
    if not isinstance(providers, dict):
        raise ConfigError("'providers' must be an object keyed by provider slug")
    for slug, settings in providers.items():
        if not isinstance(settings, dict):
            raise ConfigError(f"providers.{slug} must be an object")
        extra = sorted(set(settings) - {"credentials", "sandbox"})
        if extra:
            raise ConfigError(f"providers.{slug} has unknown keys {extra}")
        if _holds_literal_secret(settings.get("credentials")):
            _warn_if_readable_by_others(path, slug)
    return _expand(raw, "config", environ)


def _warn_if_readable_by_others(path, slug):
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        logger.warning(
            "%s holds credentials for %s and is readable by other users; "
            "run `chmod 600 %s` or use ${ENV_VAR} references instead",
            path, slug, path,
        )
