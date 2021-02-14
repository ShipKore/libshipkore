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

.. code-block:: bash

   libshipkore providers

To get all the supported Couriers.

.. code-block:: bash

   libshipkore track

To track a package in supported Couriers. It will ask for 2 things

- Provider (Couries)
- Waybill (Tracking number) 

As Library

    Coming Soon

Features
--------

- Tracking through CLI
- Embeddable as library
- Give standard response
- Convert Courier's statuses to standard statuses
- Convert date & time to timezone specific ISO Format

Sample Response
---------------

    Coming Soon

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
- 

Supported Couriers
-------------------

- `Delhivery <https://www.delhivery.com/>`_
- `Ekart <https://www.delhivery.com/>`_



Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
