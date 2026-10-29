=======
History
=======

0.5.0 (unreleased)
------------------

Breaking:

* Requires Python 3.10 or newer and pydantic 2 (pydantic 1 is no longer supported).
  Models are pydantic 2 models: use ``model_dump()`` / ``model_dump_json()`` instead of
  ``dict()`` / ``json()``. JSON output is unchanged: date-only values stay dates and UTC
  is written as ``+00:00``. A boolean is no longer accepted where text is expected.

Added:

* A carrier directory (``libshipkore carriers``, MCP ``search_carriers``), tracking without naming the
  provider when the number format identifies the carrier, and trackers described as JSON specs
  (``libshipkore/track/specs/``). The first spec is Amazon Shipping India (recorded response). Xpressbees (captcha) and Shadowfax (token in page script) are listed as not built; the Ekart scraper no longer works.

* iThink Logistics tracking (``ithink``, needs ``access_token`` and ``secret_key``) and Shiprocket
  tracking by AWB. Shiprocket's response shape is unverified.

* The command line runs on the ``Shipkore`` facade: ``libshipkore --config FILE`` (or ``LIBSHIPKORE_CONFIG``)
  with ``providers``, ``track`` (now with ``--refresh`` and stored results), ``serviceability``, ``services``,
  ``rates``, ``orders`` and ``order``. A bare ``libshipkore`` prints help and exits 0 on every Click version.
  ``providers`` now prints JSON (provider and operations) instead of a Python list. Booking and other changes
  are deliberately not in the CLI.
* A mistyped provider name is corrected in the error itself ("Did you mean delhivery?"), for every front end.
* Booking for Delhivery and Shiprocket: serviceability, rates, create, label, cancel, pickup
  and (Delhivery) NDR, through one interface: ``get_provider``.
* ``Shipkore`` facade for tracking, orders, labels, products and service types.
* An MCP server (``libshipkore-mcp``, extra ``libshipkore[mcp]``) with 19 tools, provider, order,
  product and capability-matrix resources, over stdio or local HTTP (loopback only, bearer token
  required). Tools that change something at a provider use preview-then-confirm.
* A Claude Code plugin and marketplace with four skills (track, ship an order, handle failed
  deliveries, set up), and ``AGENTS.md`` plus contributor skills for adding carriers and trackers.
* Configurable storage (memory, SQLite, SQLAlchemy, custom) and an S3-compatible file store
  for label PDFs.

Fixed:

* ``import libshipkore`` failed on Python 3.12 and later (and in any fresh ``uvx`` or virtualenv without
  setuptools): the unmaintained ``class-registry`` dependency imported ``pkg_resources`` without declaring
  it. It is replaced by a small built-in registry, and the dependency is gone.
* The ``globegistics`` alias pointed at a tracker that does not exist.
* ``bump2version`` could not run: its search patterns used single quotes while the files use double
  quotes, and the plugin manifest was not listed.
* The ``libshipkore`` command was missing from wheels built by Poetry; it is now declared in
  ``pyproject.toml``.

0.4.2 (2022-03-03)
------------------

* First coherent release that support many Indian and US based courier providers.


0.1.0 (2020-12-20)
------------------

* First release on PyPI.
