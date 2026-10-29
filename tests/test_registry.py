"""The built-in class registry, and the guarantee that motivated it."""

import subprocess
import sys

import pytest

from libshipkore.common.registry import Registry, RegistryKeyError


class Thing:
    def __init__(self, first=None, second=None, flag=False):
        self.args = (first, second, flag)


def test_register_returns_the_class_and_get_builds_one():
    registry = Registry()
    assert registry.register("thing")(Thing) is Thing  # so the decorator leaves the class alone
    made = registry.get("thing", 1, flag=True)
    assert isinstance(made, Thing) and made.args == (1, None, True)
    assert registry.get("thing") is not registry.get("thing")  # a new instance each time


def test_it_works_as_a_decorator():
    registry = Registry()

    @registry.register("decorated")
    class Decorated:
        pass

    assert Decorated.__name__ == "Decorated" and isinstance(registry.get("decorated"), Decorated)


def test_keys_membership_and_length():
    registry = Registry()
    registry.register("a")(Thing)
    registry.register("b")(Thing)
    assert registry.keys() == ["a", "b"] and "a" in registry and "z" not in registry
    assert "b" in registry.keys() and len(registry) == 2 and list(registry) == ["a", "b"]


def test_a_missing_key_is_a_keyerror_that_suggests_the_close_ones():
    registry = Registry()
    registry.register("delhivery")(Thing)
    with pytest.raises(KeyError) as error:  # callers that caught the old library's KeyError still work
        registry.get("delhivry")
    assert isinstance(error.value, RegistryKeyError)
    assert "Did you mean delhivery" in str(error.value) and "'delhivry'" in str(error.value)


def test_two_classes_cannot_share_a_name_but_re_registering_the_same_one_is_fine():
    registry = Registry()
    registry.register("x")(Thing)
    registry.register("x")(Thing)  # a module imported twice must not break
    with pytest.raises(ValueError, match="already registered"):
        registry.register("x")(type("Other", (), {}))
    assert registry.get("x").__class__ is Thing


def test_registries_are_independent():
    first, second = Registry(), Registry()
    first.register("a")(Thing)
    assert "a" not in second


def test_every_registered_name_in_the_library_is_unique_and_importable():
    from libshipkore.book.base import carrier_registry
    from libshipkore.track import track_registry
    assert len(track_registry) == 36 and len(carrier_registry) == 3
    for key in track_registry:
        module = track_registry._classes[key].__module__
        assert module.startswith("libshipkore.track.tracker.") or module == "libshipkore.track.declarative"


def test_importing_the_library_needs_no_setuptools():
    """
    Python 3.12+ virtual environments ship without setuptools, and the old
    registry dependency imported pkg_resources from it, so `import libshipkore`
    failed for every user there. Poison the import and check everything loads.
    """
    code = (
        "import sys\n"
        "sys.modules['pkg_resources'] = None  # any import of it now raises ImportError\n"
        "sys.modules['setuptools'] = None\n"
        "import libshipkore.provider, libshipkore.client, libshipkore.cli, libshipkore.book, libshipkore.track\n"
        "from libshipkore.provider import list_providers\n"
        "print(len(list_providers()))\n"
    )
    result = subprocess.run([sys.executable, "-W", "error::UserWarning", "-c", code],
                            text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "38"
    assert "pkg_resources" not in result.stderr  # and no deprecation warning either
