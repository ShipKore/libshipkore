"""Console script for libshipkore."""
import sys
import json
import click
from . import libshipkore_base
from pydantic.json import pydantic_encoder


@click.group()
def track_cli():
    pass


@click.group()
def providers_cli():
    pass


@track_cli.command()
@click.option("--provider", prompt="Provider", help="Courier partner")
@click.option(
    "--waybill",
    prompt="Waybill",
    help="Waybill or tracking number provided by provider.",
)
def track(provider, waybill):
    """Console script for libshipkore."""
    result = libshipkore_base.get_track_data(provider, waybill)
    print(json.dumps(result, indent=4, default=pydantic_encoder))
    return result


@providers_cli.command()
def providers():
    """Console script for libshipkore."""
    result = libshipkore_base.get_providers()
    print(result)
    return result


main = click.CommandCollection(sources=[track_cli, providers_cli])


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
