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

* Booking for Delhivery and Shiprocket: serviceability, rates, create, label, cancel, pickup
  and (Delhivery) NDR, through one interface: ``get_provider``.
* ``Shipkore`` facade for tracking, orders, labels, products and service types.
* An MCP server (``libshipkore-mcp``, extra ``libshipkore[mcp]``) with 19 tools over stdio or
  local HTTP, and a Claude Code plugin with skills for tracking, shipping, failed deliveries and
  setup. Tools that change something at a provider use preview-then-confirm.
* Configurable storage (memory, SQLite, SQLAlchemy, custom) and an S3-compatible file store
  for label PDFs.

Fixed:

* The ``globegistics`` alias pointed at a tracker that does not exist.

0.4.2 (2022-03-03)
------------------

* First coherent release that support many Indian and US based courier providers.


0.1.0 (2020-12-20)
------------------

* First release on PyPI.
