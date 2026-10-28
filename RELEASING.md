# Releasing libshipkore

Nothing here runs by itself. Do not tag, push or upload until you have decided the two gates below.

## Gates

1. **Has any carrier run against a real API?** `libshipkore/data/provider-capability-matrix.md` says none has: Delhivery and Shiprocket were written from their documentation and tested with mocked responses. Either run Delhivery against its staging environment (needs a staging token) and replace the hand-written fixtures in `tests/fixtures/delhivery.json` with recorded ones, or release as a clearly labelled pre-release and say so in `HISTORY.rst` and `README.rst`.
2. **`poetry.lock` is current.** It was regenerated for 0.5.0 with `uvx poetry lock --regenerate` and its exact versions were installed in a clean Python 3.12 environment and tested. Regenerate it if any dependency changed since, and `tests/test_packaging.py` will tell you if it no longer matches `pyproject.toml`.

## Checklist

- [ ] The working tree is clean. Never stage `.DS_Store`.
- [ ] `HISTORY.rst`: replace "(unreleased)" with the date.
- [ ] Versions. The first release of 0.5.0 needs no bump, because every file already says 0.5.0. For later releases run `bump2version --dry-run --verbose --allow-dirty minor` (or `patch`), read what it would change, then run it without `--dry-run`. **It makes a commit and a tag.** It updates `pyproject.toml`, `setup.py`, `libshipkore/__init__.py` and `plugin/.claude-plugin/plugin.json`; `tests/test_contributor_docs.py` fails if any of them disagrees.
- [ ] Tests on Python 3.10 and 3.13: `.venv/bin/python -m pytest -q`. The one known failure is `test_command_line_interface`.
- [ ] Lint: `.venv/bin/flake8 --ignore=E501,W503 libshipkore tests`.
- [ ] `claude plugin validate plugin` and `claude plugin validate .` both pass.
- [ ] Build: `uv build`. This makes the sdist and the wheel in `dist/`.
- [ ] Install the wheel in a clean environment, away from the source, and look at what a user gets:

  ```bash
  uv venv -p 3.12 /tmp/release-check
  uv pip install -p /tmp/release-check/bin/python "dist/libshipkore-X.Y.Z-py3-none-any.whl[mcp]"
  /tmp/release-check/bin/libshipkore-mcp --help
  /tmp/release-check/bin/libshipkore providers
  /tmp/release-check/bin/python -c "from importlib.resources import files; print(files('libshipkore').joinpath('data', 'provider-capability-matrix.md').is_file())"
  ```

  Both commands must exist, the help must print, and the last line must say `True`. Then start `libshipkore-mcp` from a client and list its tools.
- [ ] **Switch the plugin to the released package.** In `plugin/.mcp.json` replace the GitHub requirement with `"libshipkore[mcp]==X.Y.Z"`, and remove the sentence in `README.rst` that says the plugin installs from GitHub until 0.5.0 is released. A test fails if the two disagree.
- [ ] Publish. `.travis.yml` is set up to upload on a tag with an encrypted token, but nobody has checked that it still works. The `release` target in `Makefile` uploads with twine. Pick one deliberately.
- [ ] After publishing, from a machine that has never seen the repository:
  - `uvx --from "libshipkore[mcp]==X.Y.Z" libshipkore-mcp --help`
  - `claude plugin marketplace add ShipKore/libshipkore`, then `claude plugin install libshipkore@shipkore`
  - ask Claude to track a real waybill, and run the `/libshipkore:setup-libshipkore` skill.

## What this checklist cannot tell you

Whether an agent can complete a booking end to end. Until someone has run `/libshipkore:ship-order` against a staging account, treat the booking path as untested in the real world, and say that in the release notes.
