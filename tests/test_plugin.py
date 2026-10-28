"""
Tests for the Claude Code plugin and its skills.

Skills are prose, so nothing else would notice when one drifts from the tools
it tells an agent to call. These tests parse the frontmatter (a YAML mistake
makes Claude Code load a skill with no description at all), keep the manifest,
marketplace and package versions in step, and check that every tool, argument
and field a skill names still exists on the real server.
"""

import inspect
import json
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

import libshipkore  # noqa: E402
from libshipkore.book.base import OPERATIONS  # noqa: E402
from libshipkore.files import S3FileStore  # noqa: E402
from libshipkore.mcp_server.config import ALLOWED_KEYS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugin")
SKILLS = os.path.join(PLUGIN, "skills")
EXPECTED_SKILLS = {"track-shipment", "ship-order", "handle-ndr", "setup-libshipkore"}
# tools that change something at a provider and so take two calls
TWO_STEP = {"create_order", "cancel_order", "schedule_pickup", "ndr_action"}
KNOWN_FRONTMATTER = {
    "name", "description", "when_to_use", "argument-hint", "disable-model-invocation",
    "user-invocable", "allowed-tools", "model", "effort", "context", "agent", "metadata",
}
LISTING_LIMIT = 1536  # description + when_to_use are cut off beyond this in the skill list
BODY_LIMIT = 500


def read_json(*parts):
    with open(os.path.join(ROOT, *parts)) as handle:
        return json.load(handle)


def skill_files():
    return {name: os.path.join(SKILLS, name, "SKILL.md") for name in sorted(os.listdir(SKILLS))}


def parse(path):
    with open(path) as handle:
        text = handle.read()
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert match, f"{path} has no frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


# the package ---------------------------------------------------------------

def test_manifest_marketplace_and_package_agree():
    manifest = read_json("plugin", ".claude-plugin", "plugin.json")
    marketplace = read_json(".claude-plugin", "marketplace.json")
    (entry,) = marketplace["plugins"]
    assert entry["name"] == manifest["name"] == "libshipkore"  # a mismatch breaks installs
    assert entry["source"] == "./plugin" and os.path.isdir(os.path.join(ROOT, "plugin"))
    assert manifest["version"] == libshipkore.__version__
    assert marketplace["name"] == "shipkore" and marketplace["owner"]["name"]
    assert manifest["license"] == "AGPL-3.0"
    assert manifest["description"] == entry["description"]


def test_the_manifest_does_not_pass_as_an_anthropic_plugin():
    name = read_json("plugin", ".claude-plugin", "plugin.json")["name"]
    assert not re.match(r"(claude|anthropic|anthropics|cc-plugin)[-_]", name, re.I)


def test_the_server_is_started_the_way_the_package_installs_it():
    server = read_json("plugin", ".mcp.json")["mcpServers"]["libshipkore"]
    assert server["command"] == "uvx" and server["args"][-1] == "libshipkore-mcp"
    requirement = server["args"][server["args"].index("--from") + 1]
    assert requirement.startswith("libshipkore[mcp]")
    with open(os.path.join(ROOT, "pyproject.toml")) as handle:
        pyproject = handle.read()
    assert 'libshipkore-mcp = "libshipkore.mcp_server.__main__:main"' in pyproject
    assert re.search(r"^mcp = \[", pyproject, re.M)  # the extra the requirement asks for
    with open(os.path.join(ROOT, "setup.py")) as handle:
        assert "libshipkore-mcp=libshipkore.mcp_server.__main__:main" in handle.read()


def test_the_plugin_config_reaches_the_server_under_the_name_it_reads():
    manifest = read_json("plugin", ".claude-plugin", "plugin.json")
    server = read_json("plugin", ".mcp.json")["mcpServers"]["libshipkore"]
    from libshipkore.mcp_server.config import ENV_VAR
    assert server["env"] == {ENV_VAR: "${user_config.config_file}"}
    declared = manifest["userConfig"]["config_file"]
    assert declared["type"] == "file" and declared["required"] is False
    # optional, so someone who only wants tracking is never forced to write a file
    assert "sensitive" not in declared


# the skills ----------------------------------------------------------------

def test_the_expected_skills_exist_and_nothing_else_is_shipped():
    assert set(skill_files()) == EXPECTED_SKILLS
    for path in skill_files().values():
        assert os.path.isfile(path)


@pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
def test_frontmatter_is_valid_yaml_a_reader_can_use(name):
    # invalid YAML makes Claude Code load the skill with every field dropped,
    # so the skill would have no description and never be chosen
    meta, body = parse(skill_files()[name])
    assert isinstance(meta, dict), "frontmatter did not parse to a mapping"
    assert isinstance(meta["description"], str) and len(meta["description"]) > 40
    assert isinstance(meta.get("when_to_use", ""), str)
    assert set(meta) <= KNOWN_FRONTMATTER, set(meta) - KNOWN_FRONTMATTER
    assert meta.get("name", name) == name
    listing = len(meta["description"]) + len(meta.get("when_to_use", ""))
    assert listing <= LISTING_LIMIT, listing
    assert len(body.splitlines()) <= BODY_LIMIT


def test_skills_that_book_or_change_things_are_only_run_when_asked_for():
    for name in ("ship-order", "handle-ndr"):
        meta, _ = parse(skill_files()[name])
        assert meta["disable-model-invocation"] is True, name
    for name in ("track-shipment", "setup-libshipkore"):
        meta, _ = parse(skill_files()[name])
        assert not meta.get("disable-model-invocation"), name


def test_skills_that_use_the_two_step_tools_insist_on_a_real_approval():
    for name in ("ship-order", "handle-ndr"):
        _, body = parse(skill_files()[name])
        used = {tool for tool in TWO_STEP if tool in body}
        assert used, name
        assert "confirmation_token" in body, name
        assert re.search(r"wait for (the user|an explicit|explicit)", body, re.I), name
        assert "exactly the same arguments" in body, name
        assert re.search(r"preview", body, re.I) and "approval" in body, name


def test_the_setup_skill_never_asks_for_secrets_in_the_chat():
    _, body = parse(skill_files()["setup-libshipkore"])
    assert re.search(r"do not ask the user to paste", body, re.I)
    assert "${DELHIVERY_TOKEN}" in body and "chmod 600" in body
    literal = re.findall(r'"(?:api_token|password)":\s*"([^"$][^"]*)"', body)
    assert literal == [], f"a literal secret in the example config: {literal}"


def test_the_setup_skills_example_config_is_one_the_server_accepts(tmp_path):
    from libshipkore.mcp_server.config import load_config
    _, body = parse(skill_files()["setup-libshipkore"])
    example = re.search(r"```json\n(.*?)\n```", body, re.S).group(1)
    path = tmp_path / "config.json"
    path.write_text(example)
    environ = {k: "x" for k in ("DELHIVERY_TOKEN", "SHIPROCKET_EMAIL", "SHIPROCKET_PASSWORD")}
    config = load_config(str(path), environ=environ)
    assert set(config) <= ALLOWED_KEYS
    assert config["providers"]["delhivery"]["credentials"] == {"api_token": "x"}


# the skills against the real server ----------------------------------------

def property_names(schema):
    """Every field name in a JSON schema, including those of nested models."""
    names = set()

    def walk(node):
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema or {})
    return names


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def surface():
    pytest.importorskip("mcp")
    from mcp.client import Client
    from libshipkore.client import Shipkore
    from libshipkore.mcp_server.server import build_server
    from libshipkore.storage import MemoryStorage

    async with Client(build_server(Shipkore(storage=MemoryStorage()))) as client:
        tools = (await client.list_tools()).tools
    return {
        "tools": {t.name for t in tools},
        "arguments": set().union(*(property_names(t.input_schema) for t in tools)),
        "fields": set().union(*(property_names(t.output_schema) for t in tools)),
    }


# names a skill may mention that are not tools or schema fields: operations
# that list_providers reports, config-file keys, the options of the S3 file
# store (taken from its real signature), and a provider-specific option
OTHER_NAMES = (
    set(OPERATIONS) | ALLOWED_KEYS
    | set(inspect.signature(S3FileStore.__init__).parameters)
    | {"api_token", "courier_id", "config_file"}
)


@pytest.mark.anyio
@pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
async def test_every_name_a_skill_mentions_exists(name, surface):
    _, body = parse(skill_files()[name])
    mentioned = set(re.findall(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`", body))
    known = surface["tools"] | surface["arguments"] | surface["fields"] | OTHER_NAMES
    stale = sorted(mentioned - known)
    assert stale == [], f"{name} names things the server does not have: {stale}"


@pytest.mark.anyio
async def test_every_tool_a_skill_calls_exists_with_the_arguments_it_uses(surface):
    called = set()
    for path in skill_files().values():
        _, body = parse(path)
        called |= set(re.findall(r"[Cc]all `([a-z_]+)`", body))
        called |= set(re.findall(r"`([a-z]+_[a-z_]+)` with `", body))
    assert called, "no tool calls found: the pattern has drifted"
    assert called <= surface["tools"] | OTHER_NAMES, sorted(called - surface["tools"] - OTHER_NAMES)


@pytest.mark.anyio
async def test_the_workflow_skills_use_the_tools_they_need(surface):
    needs = {
        "track-shipment": {"track_shipment", "track_order", "list_providers"},
        "ship-order": {"list_providers", "check_serviceability", "get_rates", "create_order",
                       "get_label", "schedule_pickup", "get_order", "get_recorded_responses"},
        "handle-ndr": {"track_order", "list_orders", "ndr_action", "ndr_status"},
        "setup-libshipkore": {"list_providers", "check_serviceability"},
    }
    for name, tools in needs.items():
        _, body = parse(skill_files()[name])
        assert tools <= surface["tools"], name
        missing = {tool for tool in tools if f"`{tool}`" not in body}
        assert not missing, f"{name} no longer mentions {sorted(missing)}"


# Claude Code's own validator, when it is installed -------------------------

@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI is not installed")
@pytest.mark.parametrize("target", ["plugin", "."])
def test_claude_code_accepts_the_plugin_and_the_marketplace(target):
    result = subprocess.run(
        ["claude", "plugin", "validate", target], cwd=ROOT, text=True,
        capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validation passed" in result.stdout
    assert "failed to parse" not in result.stdout
