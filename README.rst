===========
libshipkore
===========

Shipkore tracking library & CLI to track packages across couriers. 
This is first Open source product of Innerkore Technologies. We are commited to do things differently. 


Installation
-------------

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


Sample Response
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
