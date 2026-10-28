===========
libshipkore
===========

Shipkore tracking library & CLI to track packages across couriers. 
This is first Open source product of Innerkore Technologies. We are commited to do things differently. 


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

To get all the supported Couriers.

.. code-block:: bash

   libshipkore track

To track a package in supported Couriers. It will ask for 2 things

- Provider (Couries)
- Waybill (Tracking number) 

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
exercised against a live API yet. See `docs/provider-capability-matrix.md`.

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

libshipkore ships an MCP server (`libshipkore-mcp`) and a Claude Code plugin with skills for
tracking, shipping an order, handling failed deliveries and setup.

.. code-block:: bash

   claude plugin marketplace add ShipKore/libshipkore
   claude plugin install libshipkore@shipkore

The plugin starts the server with `uvx` (so it needs `uv`), and until 0.5.0 is released on PyPI
it installs from GitHub. Tracking works with no setup. To book shipments, run the
`setup-libshipkore` skill: it helps you write a config file with your courier credentials as
`${ENV_VAR}` references, so no secret goes through the chat.

Any other MCP client can run the server directly:

.. code-block:: bash

   pip install "libshipkore[mcp]"
   libshipkore-mcp --config /path/config.json              # stdio, started by the client
   libshipkore-mcp --transport http --config /path/config.json   # http://127.0.0.1:8765/mcp, local only

Tools that book, cancel, schedule pickups or act on failed deliveries take two calls: a preview that
changes nothing, then a confirmation with a single-use token bound to the exact arguments. That is
a checkpoint, not proof a person approved, so the agent is told to show the preview and wait for a
real yes, and the client can ask you directly where it supports it. The HTTP transport listens on
the local machine only and requires a bearer token (`LIBSHIPKORE_MCP_TOKEN`, or one is generated).

As Code (like cloning this Repo)
-----------

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
