"""Reading SKILL.md files, shared by the tests that check them."""

import re

import yaml

KNOWN_FRONTMATTER = {
    "name", "description", "when_to_use", "argument-hint", "disable-model-invocation",
    "user-invocable", "allowed-tools", "model", "effort", "context", "agent", "metadata",
}
LISTING_LIMIT = 1536  # description + when_to_use are cut off beyond this in the skill list
BODY_LIMIT = 500


def parse(path):
    """(frontmatter, body). Invalid YAML raises, which is the point: Claude Code
    would load such a skill with every field dropped, description included."""
    with open(path) as handle:
        text = handle.read()
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert match, f"{path} has no frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


def check_frontmatter(meta, body, directory_name):
    """Assertions every skill must satisfy, wherever it lives."""
    assert isinstance(meta, dict), "frontmatter did not parse to a mapping"
    assert isinstance(meta["description"], str) and len(meta["description"]) > 40
    assert isinstance(meta.get("when_to_use", ""), str)
    assert set(meta) <= KNOWN_FRONTMATTER, set(meta) - KNOWN_FRONTMATTER
    assert meta.get("name", directory_name) == directory_name
    listing = len(meta["description"]) + len(meta.get("when_to_use", ""))
    assert listing <= LISTING_LIMIT, listing
    assert len(body.splitlines()) <= BODY_LIMIT
