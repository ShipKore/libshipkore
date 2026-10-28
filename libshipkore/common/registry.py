import difflib


class RegistryKeyError(KeyError):
    """No class is registered under this key."""

    def __str__(self):
        return self.args[0] if self.args else ""


class Registry:
    """
    Classes by name: `@registry.register("delhivery")` on a class, then
    `registry.get("delhivery", *args)` builds one.

    This replaces the unmaintained `class-registry` package, which imported
    `pkg_resources` without depending on setuptools and so broke `import
    libshipkore` on Python 3.12 and later, where virtual environments no
    longer carry setuptools.
    """

    def __init__(self):
        self._classes = {}

    def register(self, key):
        def decorator(cls):
            existing = self._classes.get(key)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"'{key}' is already registered to {existing.__module__}.{existing.__name__}"
                )
            self._classes[key] = cls
            return cls
        return decorator

    def get(self, key, *args, **kwargs):
        """A new instance of the class registered under key."""
        try:
            cls = self._classes[key]
        except KeyError:
            close = difflib.get_close_matches(str(key), self._classes, n=3)
            hint = f" Did you mean {', '.join(close)}?" if close else ""
            raise RegistryKeyError(f"No class is registered under '{key}'.{hint}") from None
        return cls(*args, **kwargs)

    def keys(self):
        return list(self._classes)

    def __contains__(self, key):
        return key in self._classes

    def __iter__(self):
        return iter(self._classes)

    def __len__(self):
        return len(self._classes)
