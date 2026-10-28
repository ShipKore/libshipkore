"""
Console script for libshipkore: tracking and read-only lookups.

Everything that changes something at a provider (booking, cancelling,
pickups, failed-delivery actions) is deliberately not here. Those need the
two-step preview and approval that the MCP server enforces; use that.
"""
import contextlib
import json
import sys

import click
import requests

from libshipkore.book.models import OrderStatus, Parcel, PaymentMode
from libshipkore.client import Shipkore
from libshipkore.common.exceptions import ShipkoreError
from libshipkore.common.serialization import to_jsonable
from libshipkore.mcp_server.config import load_config  # needs no MCP SDK
from libshipkore.provider import list_providers
from libshipkore.track.detect import search_carriers


def show(value):
    """Print a model, or a list of them, as JSON."""
    if isinstance(value, list):
        value = [to_jsonable(item) if hasattr(item, "model_dump") else item for item in value]
    elif hasattr(value, "model_dump"):
        value = to_jsonable(value)
    click.echo(json.dumps(value, indent=4))


def kore_for(ctx):
    """The Shipkore built once from --config / $LIBSHIPKORE_CONFIG, closed when the command ends."""
    root = ctx.find_root()
    if root.obj["kore"] is None:
        try:
            root.obj["kore"] = Shipkore.from_config(load_config(root.obj["config"]))
        except ShipkoreError as error:
            raise click.ClickException(str(error))
        ctx.call_on_close(root.obj["kore"].close)
    return root.obj["kore"]


@contextlib.contextmanager
def expected_failures():
    """Show an expected failure as one line and exit 1, not as a traceback."""
    try:
        yield
    except (ShipkoreError, ValueError) as error:
        raise click.ClickException(str(error))


@click.group(invoke_without_command=True)
@click.option(
    "--config", envvar="LIBSHIPKORE_CONFIG", type=click.Path(dir_okay=False),
    help="JSON config file with provider credentials and storage "
         "(or set LIBSHIPKORE_CONFIG). Without one, tracking works and nothing is kept.",
)
@click.pass_context
def main(ctx, config):
    """Track parcels and look up shipping with Indian and global couriers."""
    ctx.obj = {"config": config, "kore": None}
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.pass_context
def providers(ctx):
    """Every provider and the operations it supports."""
    show(list_providers())


@main.command()
@click.option("--provider", help="Courier, e.g. delhivery. See: carriers. Omit to guess from the number.")
@click.option("--waybill", prompt="Waybill", help="Waybill or tracking number provided by the courier.")
@click.option("--refresh", is_flag=True, help="Ask the courier again instead of using a recent stored result.")
@click.pass_context
def track(ctx, provider, waybill, refresh):
    """Where a shipment is, with its checkpoints."""
    kore = kore_for(ctx)
    try:
        with expected_failures():
            result = kore.track(waybill, provider, refresh=refresh)
    except click.ClickException:
        raise
    except requests.RequestException as error:
        raise click.ClickException(
            f"could not reach {provider} ({type(error).__name__}); try again shortly")
    except Exception as error:
        raise click.ClickException(
            f"{provider}'s tracking page or API returned something unexpected "
            f"({type(error).__name__}: {error}); it may have changed")
    show(result)


@main.command()
@click.argument("query", required=False)
@click.option("--country", help="Two-letter country code, e.g. IN.")
@click.option("--supported/--unsupported", default=None, help="Only carriers whose tracking is (or is not) built.")
def carriers(query, country, supported):
    """Search the carrier directory by name or slug."""
    show(search_carriers(query, country, supported, limit=1000))


@main.command()
@click.option("--provider", required=True, help="Courier, e.g. delhivery.")
@click.option("--pincode", required=True, help="Destination postal code.")
@click.option("--origin-pincode", help="Pickup postal code; some providers (shiprocket) need it.")
@click.pass_context
def serviceability(ctx, provider, pincode, origin_pincode):
    """Whether a provider delivers to a postal code."""
    kore = kore_for(ctx)
    with expected_failures():
        show(kore.serviceability(provider, pincode, origin_pincode))


@main.command()
@click.option("--provider", required=True, help="Courier, e.g. delhivery.")
@click.pass_context
def services(ctx, provider):
    """Service levels (Express, Surface...) a provider offers."""
    kore = kore_for(ctx)
    with expected_failures():
        show(kore.services(provider))


@main.command()
@click.option("--provider", required=True, help="Courier, e.g. delhivery.")
@click.option("--origin-pincode", required=True)
@click.option("--destination-pincode", required=True)
@click.option("--weight-kg", required=True, type=click.FloatRange(min=0, min_open=True))
@click.option("--payment-mode", type=click.Choice([m.value for m in PaymentMode]), default="Prepaid",
              show_default=True)
@click.option("--cod-amount", type=click.FloatRange(min=0), default=0, show_default=True)
@click.pass_context
def rates(ctx, provider, origin_pincode, destination_pincode, weight_kg, payment_mode, cod_amount):
    """Price quotes for one parcel (estimates, which can differ on the invoice)."""
    kore = kore_for(ctx)
    with expected_failures():
        show(kore.rates(provider, origin_pincode, destination_pincode,
                        Parcel(weight_kg=weight_kg), PaymentMode(payment_mode), cod_amount))


@main.command()
@click.option("--provider", help="Only this provider.")
@click.option("--status", type=click.Choice([s.value for s in OrderStatus]), help="Only this status.")
@click.option("--limit", type=click.IntRange(min=1, max=100), default=20, show_default=True)
@click.pass_context
def orders(ctx, provider, status, limit):
    """Stored orders, most recently changed first."""
    kore = kore_for(ctx)
    with expected_failures():
        show(kore.list_orders(provider=provider, status=status, limit=limit))


@main.command()
@click.argument("order_id")
@click.pass_context
def order(ctx, order_id):
    """One stored order with its waybill, pickup and failed-delivery history."""
    kore = kore_for(ctx)
    with expected_failures():
        show(kore.get_order(order_id))


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
