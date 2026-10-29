===========
libshipkore
===========

Shipkore: one Python interface to track parcels with 39 couriers and to book, label, cancel and manage
shipments with Indian and global carriers, plus an MCP server and a Claude Code plugin so AI agents can
use it safely. This is first Open source product of Innerkore Technologies. We are commited to do things differently.

Status: tracking is the mature part. Booking exists for Delhivery and Shiprocket and has been written
from their documentation and tested against mocked responses, but **not yet run against a live or
staging API**. See `What works today`_ below.


Installation
-------------

Requires Python 3.10 or newer and pydantic 2.

.. code-block:: python

   pip install libshipkore

Usage
-------

As CLI
-------

.. code-block:: bash

   libshipkore providers

Every provider and the operations it supports, as JSON.

.. code-block:: bash

   libshipkore track --provider delhivery --waybill 1234567890123

Where a shipment is, as JSON, with its checkpoints. Without `--waybill` it asks for it. Without
`--provider` it tries the carriers whose number format fits (few formats are distinctive enough, so name
the provider when you know it). Add `--refresh` to ask the courier again instead of using a recent stored result.

.. code-block:: bash

   libshipkore carriers delhivery
   libshipkore carriers --country IN --unsupported

Search the carrier directory: which carriers tracking is built for, and for the rest why not.

A few couriers (Ekart today) only show tracking on a page whose scripts build the request, so a plain HTTP call
cannot reach it. For those the library opens the public page in a headless browser and reads what the page itself
fetches. The order of preference is always the courier's API, then a direct request, then the browser. It needs
the extra and a browser; the library never solves captchas:

.. code-block:: bash

   pip install "libshipkore[browser]"
   playwright install chromium        # or have Google Chrome installed and set LIBSHIPKORE_BROWSER_CHANNEL=chrome

The other commands look things up and change nothing at a provider:

.. code-block:: bash

   libshipkore serviceability --provider delhivery --pincode 560001
   libshipkore services --provider delhivery
   libshipkore rates --provider delhivery --origin-pincode 110001 --destination-pincode 560001 --weight-kg 2
   libshipkore orders --provider delhivery --status Booked
   libshipkore order ORD-1

Give a config file (see "The config file" below) with `libshipkore --config /path/config.json <command>`
or the `LIBSHIPKORE_CONFIG` variable. It supplies provider credentials and storage, so `serviceability`
and `rates` can authenticate, tracking results are kept between runs, and `orders` has something to read.
Failures print one line and exit 1, not a traceback.

Booking, cancelling, pickups and failed-delivery actions are deliberately not in the CLI. They need the
two-step approval that the MCP server enforces; see "Use it from an AI agent".

As Library
-----------

.. code-block:: python

   from libshipkore.track import get_track_data
   from libshipkore.track import get_providers 

`get_track_data` provides tracking utility to track package in supported Couriers.
`get_providers` provides list of all the supported logistics providers.

One interface for every provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every provider, whether it can only track or can also book, is reached the same way.
Each one supports a subset of these operations: `track`, `serviceability`, `rates`,
`create_shipment`, `label`, `cancel`, `schedule_pickup`, `ndr_action` and `ndr_status`.
Ask `capabilities` before calling; an operation a provider lacks raises `UnsupportedOperation`.

.. code-block:: python

   from libshipkore.provider import get_provider, list_providers
   from libshipkore.book.models import Address, Parcel, ShipmentRequest

   list_providers()     # {"delhivery": ["cancel", "label", ...], "dtdc": ["track"], ...}

   delhivery = get_provider("delhivery", credentials={"api_token": "..."}, sandbox=True)
   delhivery.capabilities
   delhivery.serviceability("560001")
   shipment = delhivery.create_shipment(ShipmentRequest(...))
   delhivery.label(shipment.waybill, shipment.reference, size="4R")
   delhivery.track(shipment.waybill)

Booking is implemented for Delhivery and Shiprocket so far, and neither has been
exercised against a live API yet. See `libshipkore/data/provider-capability-matrix.md`.

The simple way in: `Shipkore`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

`Shipkore` is one client for tracking, orders, labels, products and service types.
It picks the provider, keeps your data in a storage layer you configure, and keeps
label PDFs in a separate S3-compatible file store.

.. code-block:: python

   from libshipkore.client import Shipkore
   from libshipkore.book.models import Address, Product

   shipkore = Shipkore(
       providers={"delhivery": {"credentials": {"api_token": "..."}, "sandbox": True}},
       storage="sqlite:///shipkore.db",
       files="s3://my-label-bucket/labels",
   )

   shipkore.save_product(Product(sku="TEE", name="T-shirt", price=499, weight_kg=0.3))
   order = shipkore.create_order(
       "delhivery", "ORD-1", Address(name="Asha", phone="9876543210", address="12 MG Road",
                                     pincode="560001", city="Bengaluru", state="Karnataka"),
       pickup_location="Main Warehouse", items=[{"sku": "TEE", "quantity": 2}],
   )
   shipkore.label("ORD-1")          # PDF copied to the file store, returns a download link
   shipkore.track_order("ORD-1")    # served from storage while recent
   shipkore.cancel_order("ORD-1")
   shipkore.services("delhivery")   # Express, Surface

Items refer to catalog products by sku, which fill in the declared value, parcel weight and
description unless you pass them. A failed booking is stored with its error and can be retried
under the same order id; a booked order cannot be created twice. Every raw provider response is
kept in the `responses` collection as an audit trail (`shipkore.responses(order_id="ORD-1")`);
pass `record_responses=False` to turn that off.

**Storage** (`storage=`) holds orders, products, tracking results, label records and raw
responses as JSON documents. It accepts:

- `"memory://"`, the default, for tests and scripts
- `"sqlite:///shipkore.db"`, a file with no extra dependency
- any SQLAlchemy URL such as `"postgresql://user:pw@host/db"` (`pip install libshipkore[sql]`)
- `{"backend": "pkg.module.MyStorage", ...}` or a `Storage` instance, for Redis, Mongo, Firebase
  and so on: subclass `libshipkore.storage.Storage` and implement `put`, `get`, `delete`, `list`

If `storage` is not given, the `LIBSHIPKORE_STORAGE` environment variable is used. SQL backends
filter in Python after reading a collection, which suits thousands of orders, not millions.

**File storage** (`files=`) holds label PDFs and is separate from the database. It is S3
compatible: AWS S3, MinIO, Cloudflare R2, DigitalOcean Spaces (`pip install libshipkore[s3]`).

.. code-block:: python

   files="s3://bucket/prefix"                          # AWS credentials from the usual chain
   files={"backend": "s3", "bucket": "labels", "endpoint_url": "https://minio.internal:9000",
          "access_key": "...", "secret_key": "..."}

If `files` is not given (or `LIBSHIPKORE_FILES` is unset), labels are not copied and the
provider's own link is kept until it expires; Delhivery's lasts 24 hours.


Use it from an AI agent
~~~~~~~~~~~~~~~~~~~~~~~~

Install the Claude Code plugin: it bundles the MCP server and four skills.

.. code-block:: bash

   claude plugin marketplace add ShipKore/libshipkore
   claude plugin install libshipkore@shipkore

The plugin starts the server with `uvx` (so it needs `uv`), and until 0.5.0 is released on PyPI it
installs from GitHub. Tracking works with no setup. To book shipments, run the `setup-libshipkore`
skill: it helps you write a config file with your courier credentials as `${ENV_VAR}` references,
so no secret goes through the chat.

The skills are `/libshipkore:track-shipment` and `/libshipkore:setup-libshipkore`, which Claude also
uses on its own when relevant, and `/libshipkore:ship-order` and `/libshipkore:handle-ndr`, which
book or change things and so run only when you invoke them.

What the server offers
......................

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Kind
     - Tools
   * - Look things up (change nothing)
     - `list_providers`, `check_serviceability`, `list_service_types`, `get_rates`, `track_shipment`, `search_carriers`,
       `get_order`, `list_orders`, `list_products`, `get_product`, `get_recorded_responses`
   * - Refresh and keep a result (safe to repeat)
     - `track_order`, `ndr_status`, `get_label`
   * - Edit the product catalog
     - `save_product` (refuses to replace unless asked), `delete_product`
   * - Change something at a provider (two calls each)
     - `create_order`, `cancel_order`, `schedule_pickup`, `ndr_action`

It also serves resources: `shipkore://providers`, `shipkore://orders/{order_id}`,
`shipkore://products/{sku}` and `shipkore://capability-matrix` (what each provider's API supports,
and how sure we are).

The config file
...............

A JSON file, passed with `--config` or the `LIBSHIPKORE_CONFIG` variable. With none, the server runs
with in-memory storage and no credentials, which is enough to track.

.. code-block:: json

   {
     "providers": {
       "delhivery": {"credentials": {"api_token": "${DELHIVERY_TOKEN}"}, "sandbox": true},
       "shiprocket": {"credentials": {"email": "${SR_EMAIL}", "password": "${SR_PASSWORD}"}}
     },
     "storage": "sqlite:////var/lib/shipkore/kore.db",
     "files": "s3://my-label-bucket/labels"
   }

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Key
     - Meaning
   * - `providers`
     - Per provider: `credentials` and `sandbox`. A provider you do not list can still be tracked.
   * - `sandbox`
     - Default for providers that do not say. Shiprocket has no sandbox.
   * - `storage`
     - Orders, products, tracking and the audit trail: `memory://`, `sqlite:///path`, or any
       SQLAlchemy URL. Also read from `LIBSHIPKORE_STORAGE`.
   * - `files`
     - Where label PDFs go, kept apart from the database, in any S3-compatible store. Also read
       from `LIBSHIPKORE_FILES`.
   * - `track_ttl`
     - Seconds a stored tracking result is served before asking the courier again (default 300).
   * - `label_url_expiry`
     - Seconds a download link to a stored label stays valid (default 3600).
   * - `record_responses`
     - Keep every raw provider reply as an audit trail (default true).

Write secrets as `${ENV_VAR}` references. An unknown key is rejected, so a typo is reported and not
ignored, and the server warns if the file holds literal credentials and others can read it.

If the config is invalid, or names an `${ENV_VAR}` that is not set, the server refuses to start and
Claude Code shows only "failed to connect". Run `libshipkore-mcp --config /path/config.json` in a
terminal to read the exact message.

Other MCP clients
.................

.. code-block:: bash

   pip install "libshipkore[mcp]"
   claude mcp add libshipkore -e LIBSHIPKORE_CONFIG=/path/config.json -- libshipkore-mcp

or over local HTTP:

.. code-block:: bash

   export LIBSHIPKORE_MCP_TOKEN=$(openssl rand -hex 24)
   libshipkore-mcp --transport http --config /path/config.json
   claude mcp add --transport http libshipkore http://127.0.0.1:8765/mcp --header "Authorization: Bearer $LIBSHIPKORE_MCP_TOKEN"

Options: `--transport`, `--host`, `--port`, `--no-auth`, `--no-elicit`, `--confirm-ttl`.

How writes stay safe
....................

- **Two calls, not one.** A tool that books, cancels, schedules a pickup or acts on a failed delivery
  first returns a preview and a token and changes nothing. The same call with the same arguments and
  the token performs it. The token is bound to a hash of those exact arguments, works once, expires
  after ten minutes and is stored only as a hash. A preview makes no call to the provider.
- **This is a checkpoint, not proof a person approved.** An agent can call twice in a row. The skills
  tell it to show the preview and wait for a real yes, the client's own permission prompt applies,
  and where the client supports it the server also asks you directly. On the newest MCP protocol
  version a server cannot ask mid-call, so there the token alone gates the action.
- **Credentials never travel through tools.** They come from the config file or the environment.
- **HTTP is local only.** It refuses any address that is not loopback or localhost, checks the Host and
  Origin headers so a web page cannot reach it, and requires a bearer token so other users on the
  same machine cannot use your credentials (`LIBSHIPKORE_MCP_TOKEN`, at least 16 characters, or one is
  generated and printed to stderr). `--no-auth` turns the token off and says so loudly.
- **Everything is recorded.** The raw provider replies are kept per order and can be read with
  `get_recorded_responses`.

What works today
................

.. list-table::
   :header-rows: 1
   :widths: 18 52 30

   * - Provider
     - Operations
     - Evidence
   * - Delhivery
     - serviceability, service types, rates, book (forward and reverse), label, cancel, pickup, NDR
     - Written from its developer-portal docs; not run against staging
   * - Shiprocket
     - serviceability, rates, book, label, cancel, pickup, tracking (unverified)
     - Login, order, pickup and cancel from its docs; serviceability and AWB shapes are reconstructed; no sandbox
   * - 39 couriers
     - tracking only
     - Scrapers, APIs and JSON specs; only Delhivery, Ekart and Amazon Shipping have tests

The research behind this is `libshipkore/data/provider-capability-matrix.md`, which is also served by the
MCP server. Shiprocket NDR and returns are not implemented, and the other carriers in the
matrix are not started.

As Code (like cloning this Repo)
--------------------------------

Install `poetry` first. Then, to install dependencies,

.. code-block:: bash

   poetry install

To run track command,

.. code-block:: bash

   poetry run python -m libshipkore.cli track --provider zinc --waybill ZPYAA0073001334YQ


Features
--------

- Tracking through CLI
- Embeddable as library
- One interface for tracking and booking (`get_provider`) and a `Shipkore` facade with pluggable storage
- An MCP server and a Claude Code plugin for AI agents, with approval-gated writes
- Give standard response
- Convert Courier's statuses to standard statuses
- Convert date & time to timezone specific ISO Format


Supported Statuses
------------------

- InfoReceived
- InTransit
- OutForDelivery
- AttemptFail
- Delivered
- AvailableForPickup
- Exception
- ReverseDelivered
- ReverseOutForDelivery
- ReverseInTransit


Supported Couriers
-------------------

- `Delhivery <https://www.delhivery.com/>`_
- `Ekart <https://ekartlogistics.com/>`_
- `DTDC <https://www.dtdc.com/>`_

and many many more `see here <https://github.com/ShipKore/libshipkore/tree/master/libshipkore/track/tracker>`_


Response Schema
---------------

.. code-block:: json

    {
    "title": "Track",
    "type": "object",
    "properties": {
        "checkpoints": {
        "title": "Checkpoints",
        "type": "array",
        "items": {
            "$ref": "#/definitions/Checkpoint"
        }
        },
        "waybill": {
        "title": "Waybill",
        "type": "string"
        },
        "provider": {
        "title": "Provider",
        "type": "string"
        },
        "status": {
        "default": "Exception",
        "allOf": [
            {
            "$ref": "#/definitions/StatusChoice"
            }
        ]
        },
        "substatus": {
        "title": "Substatus",
        "type": "string"
        },
        "estimated_date": {
        "title": "Estimated Date",
        "anyOf": [
            {
            "type": "string",
            "format": "date-time"
            },
            {
            "type": "string",
            "format": "date"
            }
        ]
        },
        "reference_no": {
        "title": "Reference No",
        "type": "string"
        },
        "package_type": {
        "title": "Package Type",
        "type": "string"
        },
        "destination": {
        "title": "Destination",
        "type": "string"
        },
        "client": {
        "title": "Client",
        "type": "string"
        },
        "consignee_address": {
        "title": "Consignee Address",
        "type": "string"
        },
        "product": {
        "title": "Product",
        "type": "string"
        },
        "receiver_name": {
        "title": "Receiver Name",
        "type": "string"
        },
        "delivered_date": {
        "title": "Delivered Date",
        "anyOf": [
            {
            "type": "string",
            "format": "date-time"
            },
            {
            "type": "string",
            "format": "date"
            }
        ]
        }
    },
    "required": [
        "checkpoints",
        "waybill",
        "provider"
    ],
    "definitions": {
        "StatusChoice": {
        "title": "StatusChoice",
        "description": "An enumeration.",
        "enum": [
            "InfoReceived",
            "InTransit",
            "OutForDelivery",
            "AttemptFail",
            "Delivered",
            "AvailableForPickup",
            "Exception",
            "ReverseDelivered",
            "ReverseOutForDelivery",
            "ReverseInTransit"
        ],
        "type": "string"
        },
        "Checkpoint": {
        "title": "Checkpoint",
        "type": "object",
        "properties": {
            "slug": {
            "title": "Slug",
            "type": "string"
            },
            "city": {
            "title": "City",
            "type": "string"
            },
            "location": {
            "title": "Location",
            "type": "string"
            },
            "country_name": {
            "title": "Country Name",
            "type": "string"
            },
            "message": {
            "title": "Message",
            "type": "string"
            },
            "submessage": {
            "title": "Submessage",
            "type": "string"
            },
            "country_iso3": {
            "title": "Country Iso3",
            "type": "string"
            },
            "status": {
            "default": "Exception",
            "allOf": [
                {
                "$ref": "#/definitions/StatusChoice"
                }
            ]
            },
            "substatus": {
            "title": "Substatus",
            "type": "string"
            },
            "checkpoint_time": {
            "title": "Checkpoint Time",
            "anyOf": [
                {
                "type": "string",
                "format": "date-time"
                },
                {
                "type": "string",
                "format": "date"
                }
            ]
            },
            "state": {
            "title": "State",
            "type": "string"
            },
            "zip": {
            "title": "Zip",
            "type": "string"
            }
        },
        "required": [
            "slug",
            "checkpoint_time"
        ]
        }
    }
    }


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
