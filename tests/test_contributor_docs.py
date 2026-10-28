"""
Tests that keep AGENTS.md and the contributor skills true.

Contributor docs rot faster than code: a renamed file or a changed command
leaves them describing something that is gone, and an agent follows them
anyway. These check that what they name exists and that what they claim
about the repo matches the repo.
"""

import configparser
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

pytest.importorskip("yaml")

import libshipkore  # noqa: E402
from libshipkore.track import track_registry  # noqa: E402
from tests.skillmd import check_frontmatter, parse  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, ".claude", "skills")
EXPECTED = {"add-carrier", "add-tracker"}
FILES = {
    "AGENTS.md": os.path.join(ROOT, "AGENTS.md"),
    "CLAUDE.md": os.path.join(ROOT, "CLAUDE.md"),
    **{name: os.path.join(SKILLS, name, "SKILL.md") for name in sorted(EXPECTED)},
}
PATH_PREFIXES = ("libshipkore/", "tests/", "docs/", "plugin/", ".claude/", ".claude-plugin/")
# files at the repository root that a doc may name
ROOT_FILES = re.compile(r"[A-Za-z0-9_.-]+\.(?:toml|py|cfg|lock|ini|json|rst|md)")
# words in backticks that look like code names but are not ours
NOT_OURS = {"pkg_resources"}


def text_of(name):
    with open(FILES[name]) as handle:
        return handle.read()


def inline_code(name):
    """Everything in `backticks` outside fenced code blocks."""
    prose = re.sub(r"```.*?```", "", text_of(name), flags=re.S)
    return set(re.findall(r"`([^`\n]+)`", prose))


def source_text():
    chunks = []
    for folder in ("libshipkore", "tests"):
        for directory, _, names in os.walk(os.path.join(ROOT, folder)):
            for filename in names:
                if filename.endswith(".py"):
                    with open(os.path.join(directory, filename)) as handle:
                        chunks.append(handle.read())
    return "\n".join(chunks)


# structure -----------------------------------------------------------------

def test_claude_md_imports_agents_md():
    lines = [line for line in text_of("CLAUDE.md").splitlines() if line.strip()]
    assert lines[0] == "@AGENTS.md"
    assert os.path.isfile(FILES["AGENTS.md"])


def test_the_contributor_skills_are_the_ones_expected_and_stay_out_of_the_plugin():
    assert set(os.listdir(SKILLS)) == EXPECTED
    shipped = set(os.listdir(os.path.join(ROOT, "plugin", "skills")))
    assert not shipped & EXPECTED, "contributor skills must not ship to users"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_contributor_skill_frontmatter_is_valid(name):
    meta, body = parse(FILES[name])
    check_frontmatter(meta, body, name)
    assert not meta.get("disable-model-invocation")  # found by what the user asks for


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI is not installed")
def test_claude_code_accepts_the_contributor_skills(tmp_path):
    # the validator takes plugins, so wrap a copy of the skills in a throwaway one
    plugin = tmp_path / "contributor-skills"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "contributor-skills"}))
    shutil.copytree(SKILLS, plugin / "skills")
    result = subprocess.run(["claude", "plugin", "validate", str(plugin)], text=True,
                            capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failed to parse" not in result.stdout


# what they name exists ------------------------------------------------------

@pytest.mark.parametrize("name", sorted(FILES))
def test_every_repo_path_a_doc_names_exists(name):
    checked = []
    for token in inline_code(name):
        if any(c in token for c in "<>*{}$ ()") or token.startswith((".venv", "~")):
            continue
        if token.startswith(PATH_PREFIXES) or ROOT_FILES.fullmatch(token):
            checked.append(token)
            assert os.path.exists(os.path.join(ROOT, token.rstrip("/"))), f"{name} names {token}"
    assert checked or name == "CLAUDE.md", f"{name}: no paths found; the pattern has drifted"


CODE_NAME = re.compile(
    r"_?[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"   # snake_case, including _private
    r"|[A-Z][a-z]+(?:[A-Z][a-z0-9]*)*"            # CamelCase
    r"|[A-Z][A-Z_]{3,}"                            # CONSTANT
)


@pytest.mark.parametrize("name", sorted(FILES))
def test_every_class_function_and_constant_a_doc_names_exists(name):
    code = source_text()
    names = set()
    for token in inline_code(name):
        if token.startswith(PATH_PREFIXES) or ROOT_FILES.fullmatch(token):
            continue  # a file path: test_path_a_doc_names_exists checks those
        # words inside a longer span count too: ProviderError(self.provider, ...)
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", token):
            if CODE_NAME.fullmatch(word) and word not in NOT_OURS:
                names.add(word)
    assert len(names) > 5 or name == "CLAUDE.md", f"{name}: the pattern has drifted"
    missing = sorted(n for n in names if not re.search(rf"\b{re.escape(n)}\b", code))
    assert not missing, f"{name} names things that are not in the code: {missing}"


# what they claim about the repo is true -------------------------------------

def test_the_commands_match_the_repo_s_own_settings():
    tox = configparser.ConfigParser()
    tox.read(os.path.join(ROOT, "tox.ini"))
    ignore = re.sub(r"\s+", "", tox["flake8"]["ignore"])
    for name in ("AGENTS.md", "add-carrier", "add-tracker"):
        # the whole list, not a prefix of it: --ignore=E501 must not satisfy --ignore=E501,W503
        assert re.findall(r"--ignore=([A-Z0-9,]+)", text_of(name)) == [ignore], name
    agents = text_of("AGENTS.md")
    with open(os.path.join(ROOT, "pyproject.toml")) as handle:
        pyproject = handle.read()
    assert 'python = "^3.10"' in pyproject and "Python >= 3.10" in agents
    extras = re.search(r'-e "\.\[([a-z,]+)\]"', agents).group(1).split(",")
    for extra in extras:
        assert re.search(rf"^{extra} = \[", pyproject, re.M), extra


def test_the_setuptools_pin_is_still_needed():
    spec = importlib.util.find_spec("class_registry.entry_points")
    assert "pkg_resources" in pathlib.Path(spec.origin).read_text()
    assert 'setuptools<81' in text_of("AGENTS.md")


def test_the_courier_count_is_true():
    claimed = int(re.search(r"(\d+) couriers", text_of("AGENTS.md")).group(1))
    assert claimed == len(list(track_registry.keys()))


def test_the_known_failing_test_is_named_correctly():
    name = re.search(r"`(test_\w+)` in `(tests/\S+)`", text_of("AGENTS.md"))
    with open(os.path.join(ROOT, name.group(2))) as handle:
        assert f"def {name.group(1)}(" in handle.read()


def test_every_file_that_holds_the_version_holds_this_one():
    # AGENTS.md lists them; if one drifts, a release ships with two versions
    holders = ["pyproject.toml", "setup.py", "libshipkore/__init__.py", "setup.cfg",
               "plugin/.claude-plugin/plugin.json"]
    for holder in holders:
        assert holder in text_of("AGENTS.md").replace("`", ""), holder
        with open(os.path.join(ROOT, holder)) as handle:
            assert libshipkore.__version__ in handle.read(), holder


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_ds_store_warning_matches_what_git_tracks():
    listing = subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, capture_output=True)
    if listing.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = any(path.endswith(".DS_Store") for path in listing.stdout.splitlines())
    warns = "tracked by mistake" in text_of("AGENTS.md")
    assert tracked == warns, "AGENTS.md and the repository disagree about .DS_Store"
