"""The README is the first thing a user reads; keep it true to the code."""

import json
import os
import re

import pytest

pytest.importorskip("mcp")

from mcp.client import Client  # noqa: E402

from libshipkore.client import Shipkore  # noqa: E402
from libshipkore.mcp_server.__main__ import build_parser  # noqa: E402
from libshipkore.mcp_server.config import ALLOWED_KEYS  # noqa: E402
from libshipkore.mcp_server.server import build_server  # noqa: E402
from libshipkore.storage import MemoryStorage  # noqa: E402
from libshipkore.track import track_registry  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def section(text, title):
    """The text under a heading (its underline follows it), up to the next heading of the same kind."""
    match = re.search(rf"^{re.escape(title)}\n([.~=-])\1+\n(.*?)(?=^[^\n]+\n\1{{4,}}\n|\Z)", text, re.M | re.S)
    assert match, f"no section titled {title!r}"
    return match.group(2)


@pytest.fixture
def readme():
    with open(os.path.join(ROOT, "README.rst")) as handle:
        return handle.read()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_every_tool_and_resource_the_server_has_is_in_the_readme(readme):
    async with Client(build_server(Shipkore(storage=MemoryStorage()))) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        resources = {str(r.uri) for r in (await client.list_resources()).resources}
        templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
    for tool in tools:
        assert f"`{tool}`" in readme, f"README does not mention the tool {tool}"
    for uri in resources | templates:
        assert uri in readme, f"README does not mention the resource {uri}"
    mentioned = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", section(readme, "What the server offers")))
    assert mentioned == tools, f"the tool table and the server disagree: {mentioned ^ tools}"


def test_every_config_key_is_explained(readme):
    config = section(readme, "The config file")
    for key in ALLOWED_KEYS:
        assert f"`{key}`" in config, f"README does not explain the config key {key}"
    example = re.search(r"\.\. code-block:: json\n\n(.*?)\n\n", config, re.S).group(1)
    assert set(json.loads(example)) <= ALLOWED_KEYS


def test_the_commands_use_options_that_exist(readme):
    accepted = set(build_parser()._option_string_actions)
    used = set()
    for line in readme.splitlines():
        if "libshipkore-mcp" in line:
            used |= set(re.findall(r"--[a-z][a-z-]*", line.split("libshipkore-mcp", 1)[1]))
        if line.startswith("Options:"):
            used |= set(re.findall(r"--[a-z][a-z-]*", line))
    assert used >= {"--config", "--transport", "--no-auth", "--no-elicit", "--confirm-ttl"}, used
    assert used <= accepted, f"README names options the server lacks: {used - accepted}"
    # and every option the server has is documented
    undocumented = {o for o in accepted if o.startswith("--") and o != "--help" and o not in readme}
    assert not undocumented, f"the server has options the README does not mention: {undocumented}"


def test_the_plugin_commands_name_the_real_marketplace_and_plugin(readme):
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as handle:
        marketplace = json.load(handle)
    plugin = marketplace["plugins"][0]["name"]
    assert f"claude plugin install {plugin}@{marketplace['name']}" in readme
    assert "claude plugin marketplace add ShipKore/libshipkore" in readme
    skills = set(os.listdir(os.path.join(ROOT, "plugin", "skills")))
    named = set(re.findall(rf"/{plugin}:([a-z-]+)", readme))
    assert named and named <= skills, named - skills


def test_the_courier_count_is_true_everywhere_it_appears(readme):
    claims = re.findall(r"(\d+) couriers", readme)
    assert len(claims) >= 2, "the README no longer states the courier count"
    assert set(claims) == {str(len(list(track_registry.keys())))}, claims


def test_where_the_plugin_installs_from_matches_what_the_readme_says(readme):
    with open(os.path.join(ROOT, "plugin", ".mcp.json")) as handle:
        args = json.load(handle)["mcpServers"]["libshipkore"]["args"]
    from_github = any("git+https://github.com" in arg for arg in args)
    says_github = "it\ninstalls from GitHub" in readme or "installs from GitHub" in readme
    assert from_github == says_github, "plugin/.mcp.json and the README disagree about where it installs from"


def test_the_readme_says_plainly_that_nothing_has_run_live(readme):
    assert "not yet run against a live or\nstaging API" in readme or "not yet run against a live or staging API" in readme


def test_the_cli_commands_in_the_readme_are_the_ones_that_exist(readme):
    from libshipkore import cli
    cli_section = section(readme, "As CLI")
    documented = set(re.findall(r"^   libshipkore (?:--config \S+ )?([a-z]+)", cli_section, re.M))
    assert documented == set(cli.main.commands), documented ^ set(cli.main.commands)
    # every option shown in a README example is one the command accepts
    for line in re.findall(r"^   libshipkore (.*)$", cli_section, re.M):
        words = line.split()
        command = next(w for w in words if w in cli.main.commands)
        accepted = {opt for param in cli.main.commands[command].params for opt in param.opts}
        used = {w for w in words if w.startswith("--") and w != "--config"}
        assert used <= accepted, f"{command}: README uses {used - accepted}"
    assert "--refresh" in cli_section and "LIBSHIPKORE_CONFIG" in cli_section
