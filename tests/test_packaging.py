"""pyproject.toml, setup.py and poetry.lock each describe the same dependencies; keep them in step."""

import os
import re

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = pytest.importorskip("tomli")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


@pytest.fixture(scope="module")
def pyproject():
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        return tomllib.load(handle)["tool"]["poetry"]


@pytest.fixture(scope="module")
def lock():
    with open(os.path.join(ROOT, "poetry.lock"), "rb") as handle:
        return tomllib.load(handle)


@pytest.fixture(scope="module")
def setup_py():
    with open(os.path.join(ROOT, "setup.py")) as handle:
        return handle.read()


def names_in(block):
    return {normalise(re.match(r"[A-Za-z0-9_.-]+", item).group(0)) for item in re.findall(r'"([^"]+)"', block)}


def test_setup_py_and_pyproject_declare_the_same_dependencies(pyproject, setup_py):
    declared = {normalise(n) for n in pyproject["dependencies"] if n != "python"}
    optional = {normalise(n) for n, spec in pyproject["dependencies"].items()
                if isinstance(spec, dict) and spec.get("optional")}
    required = names_in(re.search(r"requirements = \[(.*?)\n\]", setup_py, re.S).group(1))
    assert required == declared - optional, required ^ (declared - optional)


def test_setup_py_and_pyproject_declare_the_same_extras(pyproject, setup_py):
    extras = {k: {normalise(n) for n in v} for k, v in pyproject["extras"].items()}
    block = re.search(r"extras_require=\{(.*?)\n    \},", setup_py, re.S).group(1)
    in_setup = {key: names_in(values) for key, values in
                re.findall(r'"(\w+)": \[(.*?)\]', block, re.S)}
    assert in_setup == extras, (in_setup, extras)


def test_the_python_floor_agrees_everywhere(pyproject, setup_py, lock):
    assert pyproject["dependencies"]["python"] == "^3.10"
    assert 'python_requires=">=3.10"' in setup_py
    assert lock["metadata"]["python-versions"] == "^3.10"


def test_the_lock_matches_pyproject(pyproject, lock):
    locked = {}
    for package in lock["package"]:
        locked.setdefault(normalise(package["name"]), []).append(package["version"])
    for name, spec in pyproject["dependencies"].items():
        if name != "python":
            assert normalise(name) in locked, f"{name} is declared but not locked: run `uvx poetry lock --regenerate`"
    assert lock["extras"].keys() == pyproject["extras"].keys()
    assert all(v.startswith("2.") for n, vs in locked.items() if n == "pydantic" for v in vs)


def test_the_lock_has_no_trace_of_the_dependency_we_removed(lock):
    names = {normalise(p["name"]) for p in lock["package"]}
    assert "class-registry" not in names
    assert "setuptools" not in names  # nothing needs it at runtime any more
