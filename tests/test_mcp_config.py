"""Tests for the MCP server's config loading; needs no MCP SDK."""

import json
import logging
import os

import pytest

from libshipkore.common.exceptions import ConfigError
from libshipkore.mcp_server.config import ENV_VAR, load_config


def write(tmp_path, content, mode=0o600):
    path = tmp_path / "config.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    os.chmod(path, mode)
    return str(path)


def test_no_config_means_defaults():
    assert load_config(environ={}) == {}


def test_a_file_becomes_shipkore_arguments(tmp_path):
    config = load_config(write(tmp_path, {
        "providers": {"delhivery": {"credentials": {"api_token": "tok"}, "sandbox": True}},
        "storage": "sqlite:///x.db",
        "files": "s3://bucket/labels",
        "track_ttl": 60,
    }), environ={})
    assert config["providers"]["delhivery"]["credentials"] == {"api_token": "tok"}
    assert config["storage"] == "sqlite:///x.db" and config["track_ttl"] == 60


def test_the_environment_variable_names_the_file(tmp_path):
    path = write(tmp_path, {"track_ttl": 5})
    assert load_config(environ={ENV_VAR: path}) == {"track_ttl": 5}
    other = tmp_path / "other.json"
    other.write_text('{"track_ttl": 9}')
    assert load_config(str(other), environ={ENV_VAR: path}) == {"track_ttl": 9}


def test_env_references_keep_secrets_out_of_the_file(tmp_path):
    path = write(tmp_path, {
        "providers": {"shiprocket": {"credentials": {
            "email": "${SR_EMAIL}", "password": "pw-${SR_SUFFIX}"}}},
        "storage": "${DB_URL}",
    })
    config = load_config(path, environ={
        "SR_EMAIL": "a@b.c", "SR_SUFFIX": "1", "DB_URL": "sqlite:///k.db"})
    assert config["providers"]["shiprocket"]["credentials"] == {
        "email": "a@b.c", "password": "pw-1"}
    assert config["storage"] == "sqlite:///k.db"


def test_a_missing_environment_variable_is_named(tmp_path):
    path = write(tmp_path, {"providers": {"delhivery": {"credentials": {
        "api_token": "${DELHIVERY_TOKEN}"}}}})
    with pytest.raises(ConfigError, match="DELHIVERY_TOKEN.*not set"):
        load_config(path, environ={})


@pytest.mark.parametrize("content, message", [
    ('{"sandbx": true}', "unknown config keys"),
    ('{"providers": []}', "keyed by provider"),
    ('{"providers": {"d": "x"}}', "providers.d must be an object"),
    ('{"providers": {"d": {"credential": {}}}}', "unknown keys"),
    ("[1, 2]", "JSON object"),
    ("{not json", "cannot read"),
])
def test_invalid_configs_are_rejected_with_the_reason(tmp_path, content, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, content), environ={})


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(str(tmp_path / "nope.json"), environ={})


def literal_secret_config():
    return {"providers": {"delhivery": {"credentials": {"api_token": "tok"}}}}


def test_a_readable_file_with_a_literal_secret_warns(tmp_path, caplog):
    path = write(tmp_path, literal_secret_config(), mode=0o644)
    with caplog.at_level(logging.WARNING, logger="libshipkore.mcp"):
        load_config(path, environ={})
    assert "readable by other users" in caplog.text and "chmod 600" in caplog.text


def test_no_warning_for_a_private_file_or_env_references(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="libshipkore.mcp"):
        load_config(write(tmp_path, literal_secret_config(), mode=0o600), environ={})
        load_config(write(tmp_path, {"providers": {"delhivery": {"credentials": {
            "api_token": "${T}"}}}}, mode=0o644), environ={"T": "x"})
    assert caplog.text == ""
