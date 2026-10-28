"""Tests for the MCP server, driven through the SDK's own client."""

import json
import os
import sys

import pytest
import requests
import responses

pytest.importorskip("mcp")

from mcp import StdioServerParameters  # noqa: E402
from mcp.client import Client  # noqa: E402

from libshipkore.book.models import Address, Product  # noqa: E402
from libshipkore.client import Shipkore  # noqa: E402
from libshipkore.mcp_server.server import build_server  # noqa: E402
from libshipkore.storage import MemoryStorage  # noqa: E402
from libshipkore.track.models.model import Checkpoint, Track  # noqa: E402

pytestmark = pytest.mark.anyio

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
DELHIVERY = "https://track.delhivery.com"
with open(os.path.join(HERE, "fixtures", "delhivery.json")) as f:
    DLV = json.load(f)

PROVIDERS = {
    "delhivery": {"credentials": {"api_token": "tok"}, "sandbox": False},
    "shiprocket": {"credentials": {"email": "a@b.c", "password": "pw"}},
}
LOOKUP_TOOLS = {
    "list_providers", "check_serviceability", "list_service_types", "get_rates",
    "track_shipment", "get_order", "list_orders", "list_products", "get_product",
    "get_recorded_responses",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def kore():
    shipkore = Shipkore(providers=PROVIDERS, storage=MemoryStorage())
    shipkore.save_product(Product(sku="TEE", name="T-shirt", price=499, weight_kg=0.3))
    return shipkore


@pytest.fixture
async def client(kore):
    async with Client(build_server(kore)) as connected:
        yield connected


def text(result):
    return result.content[0].text


def data(result):
    """The structured result, unwrapped from the {"result": ...} the SDK adds to lists."""
    assert not result.is_error, text(result)
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


def book(kore, order_id="ORD-1"):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/api/cmu/create.json", json=DLV["create_ok"])
        return kore.create_order(
            "delhivery", order_id,
            Address(name="Asha", phone="9876543210", address="12 MG Road",
                    pincode="560001", city="Bengaluru", state="Karnataka"),
            "Main WH", items=[{"sku": "TEE", "quantity": 2}],
        )


def make_track(status="InTransit"):
    return Track(
        waybill="1234567890123", provider="delhivery", status=status,
        checkpoints=[Checkpoint(slug="delhivery", message="scan",
                                checkpoint_time="2026-01-02T03:04:05+05:30")],
    )


# surface -------------------------------------------------------------------

async def test_the_tools_are_documented_and_annotated(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert LOOKUP_TOOLS <= set(tools) and "track_order" in tools
    for name, tool in tools.items():
        assert tool.title and tool.description, name
        assert tool.annotations is not None, name
        assert not tool.annotations.destructive_hint, name
    for name in LOOKUP_TOOLS:
        assert tools[name].annotations.read_only_hint is True, name
    # it records the delivery status on the order, so it must not claim read-only
    assert tools["track_order"].annotations.read_only_hint is False
    assert tools["track_order"].annotations.idempotent_hint is True


async def test_every_parameter_is_described(client):
    for tool in (await client.list_tools()).tools:
        for name, schema in tool.input_schema.get("properties", {}).items():
            described = schema.get("description") or any(
                "description" in option for option in schema.get("anyOf", []))
            assert described, (tool.name, name)


async def test_the_server_tells_agents_where_to_start(client):
    assert "list_providers" in client.instructions
    assert "Never ask the user to paste" in client.instructions


# list_providers ------------------------------------------------------------

async def test_providers_report_capabilities_and_what_is_configured(client):
    providers = {p["slug"]: p for p in data(await client.call_tool("list_providers", {}))}
    assert providers["delhivery"]["configured"] is True
    assert "create_shipment" in providers["delhivery"]["operations"]
    assert providers["shiprocket"]["operations"] == sorted(providers["shiprocket"]["operations"])
    assert providers["dtdc"] == {
        "slug": "dtdc", "operations": ["track"], "configured": False, "sandbox": False}
    assert "api_token" not in json.dumps(providers)  # credentials never leave the server


# lookups -------------------------------------------------------------------

async def test_check_serviceability(client):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, DELHIVERY + "/c/api/pin-codes/json/",
                 json=DLV["serviceability_ok"])
        result = data(await client.call_tool(
            "check_serviceability", {"provider": "delhivery", "pincode": "110001"}))
    assert result["serviceable"] is True and result["pincode"] == "110001"


async def test_get_rates_sends_the_parcel(client):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, DELHIVERY + "/api/kinko/v1/invoice/charges/.json",
                 json=DLV["rates"])
        result = data(await client.call_tool("get_rates", {
            "provider": "delhivery", "origin_pincode": "110001",
            "destination_pincode": "560001", "weight_kg": 2, "payment_mode": "COD",
            "length_cm": 30}))
        query = rsps.calls[0].request.url
    assert result[0]["amount"] == 85.5 and result[0]["currency"] == "INR"
    assert "cgm=2000" in query and "pt=COD" in query and "l=30" in query


async def test_list_service_types(client):
    result = data(await client.call_tool("list_service_types", {"provider": "delhivery"}))
    assert [(s["code"], s["name"]) for s in result] == [("E", "Express"), ("S", "Surface")]


async def test_track_shipment_and_its_cache(client, monkeypatch):
    calls = []
    monkeypatch.setattr("libshipkore.book.base.get_track_data",
                        lambda slug, waybill: calls.append(slug) or make_track())
    args = {"provider": "delhivery", "waybill": "1234567890123"}
    first = data(await client.call_tool("track_shipment", args))
    assert first["status"] == "InTransit"
    assert first["checkpoints"][0]["checkpoint_time"] == "2026-01-02T03:04:05+05:30"
    await client.call_tool("track_shipment", args)
    assert len(calls) == 1
    await client.call_tool("track_shipment", {**args, "refresh": True})
    assert len(calls) == 2


async def test_track_works_for_a_provider_with_no_credentials(client, monkeypatch):
    monkeypatch.setattr("libshipkore.book.base.get_track_data", lambda s, w: make_track())
    assert data(await client.call_tool("track_shipment", {"provider": "dtdc", "waybill": "1"}))


# orders, products, audit trail ---------------------------------------------

async def test_orders_and_products(client, kore, monkeypatch):
    book(kore)
    book(kore, "ORD-2")
    one = data(await client.call_tool("get_order", {"order_id": "ORD-1"}))
    assert one["waybill"] == "1234567890123" and one["status"] == "Booked"
    assert one["description"] == "T-shirt x2"
    listed = data(await client.call_tool("list_orders", {"provider": "delhivery"}))
    assert [o["order_id"] for o in listed] == ["ORD-2", "ORD-1"]
    paged = data(await client.call_tool("list_orders", {"limit": 1, "offset": 1}))
    assert [o["order_id"] for o in paged] == ["ORD-1"]
    assert data(await client.call_tool("list_orders", {"status": "Cancelled"})) == []
    assert data(await client.call_tool("get_product", {"sku": "TEE"}))["price"] == 499
    assert [p["sku"] for p in data(await client.call_tool("list_products", {}))] == ["TEE"]


async def test_track_order_records_the_delivery_status(client, kore, monkeypatch):
    book(kore)
    monkeypatch.setattr("libshipkore.book.base.get_track_data",
                        lambda s, w: make_track("OutForDelivery"))
    result = data(await client.call_tool("track_order", {"order_id": "ORD-1"}))
    assert result["status"] == "OutForDelivery"
    assert kore.get_order("ORD-1").delivery_status == "OutForDelivery"


async def test_recorded_responses_are_shortened_on_request(client, kore):
    book(kore)
    full = data(await client.call_tool("get_recorded_responses", {"order_id": "ORD-1"}))
    assert full[0]["operation"] == "create_shipment" and full[0]["truncated"] is False
    assert "1234567890123" in full[0]["body"]
    short = data(await client.call_tool(
        "get_recorded_responses", {"order_id": "ORD-1", "max_body_chars": 10}))
    assert len(short[0]["body"]) == 10 and short[0]["truncated"] is True
    assert data(await client.call_tool(
        "get_recorded_responses", {"order_id": "nope"})) == []


# errors an agent can act on ------------------------------------------------

async def test_a_mistyped_provider_gets_a_suggestion(client):
    result = await client.call_tool(
        "check_serviceability", {"provider": "delhivry", "pincode": "110001"})
    assert result.is_error
    assert "Did you mean delhivery" in text(result) and "list_providers" in text(result)


async def test_an_unsupported_operation_lists_what_is_supported(client):
    result = await client.call_tool("list_service_types", {"provider": "shiprocket"})
    assert result.is_error
    message = text(result)
    assert "Not supported" in message and "shiprocket supports:" in message
    assert "create_shipment" in message


async def test_missing_credentials_point_at_the_config_not_the_chat(monkeypatch):
    bare = Shipkore(storage=MemoryStorage())
    async with Client(build_server(bare)) as client:
        result = await client.call_tool(
            "check_serviceability", {"provider": "delhivery", "pincode": "110001"})
    assert result.is_error
    message = text(result)
    assert "api_token" in message and "config" in message
    assert "paste secrets into the chat" in message


async def test_a_provider_rejection_carries_its_status_and_words(client):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, DELHIVERY + "/c/api/pin-codes/json/",
                 status=401, body="Invalid Token")
        result = await client.call_tool(
            "check_serviceability", {"provider": "delhivery", "pincode": "110001"})
    message = text(result)
    assert result.is_error and "HTTP 401" in message and "Invalid Token" in message


async def test_a_missing_order_says_so(client):
    result = await client.call_tool("get_order", {"order_id": "ghost"})
    assert result.is_error and "no order 'ghost'" in text(result)


async def test_invalid_arguments_are_rejected_before_any_call(client):
    for arguments in (
        {"provider": "delhivery", "origin_pincode": "1", "destination_pincode": "560001",
         "weight_kg": 1},
        {"provider": "delhivery", "origin_pincode": "110001",
         "destination_pincode": "560001", "weight_kg": 0},
        {"provider": "delhivery", "origin_pincode": "110001",
         "destination_pincode": "560001", "weight_kg": 1, "payment_mode": "Barter"},
    ):
        assert (await client.call_tool("get_rates", arguments)).is_error
    assert (await client.call_tool("list_orders", {"limit": 0})).is_error
    assert (await client.call_tool("list_orders", {"limit": 101})).is_error


async def test_tracker_failures_are_explained_not_hidden(client, monkeypatch):
    def broken(slug, waybill):
        raise KeyError("shipmentTrackingDetails")

    def offline(slug, waybill):
        raise requests.ConnectionError("down")

    args = {"provider": "ekart", "waybill": "1"}
    monkeypatch.setattr("libshipkore.book.base.get_track_data", broken)
    assert "may have changed" in text(await client.call_tool("track_shipment", args))
    monkeypatch.setattr("libshipkore.book.base.get_track_data", offline)
    assert "Could not reach the provider" in text(await client.call_tool("track_shipment", args))


async def test_a_real_bug_is_not_leaked_to_the_model(client, monkeypatch):
    def boom(*args):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("libshipkore.client.Shipkore.get_product", boom)
    result = await client.call_tool("get_product", {"sku": "TEE"})
    assert result.is_error and "secret internal detail" not in text(result)


# resources -----------------------------------------------------------------

async def test_resources(client, kore):
    book(kore)
    uris = {str(r.uri) for r in (await client.list_resources()).resources}
    assert "shipkore://providers" in uris
    templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
    assert {"shipkore://orders/{order_id}", "shipkore://products/{sku}"} <= templates

    providers = json.loads((await client.read_resource("shipkore://providers")).contents[0].text)
    assert "delhivery" in providers
    order = json.loads((await client.read_resource("shipkore://orders/ORD-1")).contents[0].text)
    assert order["waybill"] == "1234567890123"
    product = json.loads((await client.read_resource("shipkore://products/TEE")).contents[0].text)
    assert product["name"] == "T-shirt"


async def test_a_missing_resource_is_an_error(client):
    with pytest.raises(Exception, match="no order"):
        await client.read_resource("shipkore://orders/ghost")


# the real thing: a subprocess speaking the protocol over stdio -------------

async def test_the_server_runs_as_a_real_stdio_process(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"providers": {"dtdc": {"credentials": {}}}}))
    config.chmod(0o600)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "libshipkore.mcp_server", "--config", str(config)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": ROOT},
    )
    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert LOOKUP_TOOLS <= names
        providers = data(await client.call_tool("list_providers", {}))
        assert {p["slug"]: p["configured"] for p in providers}["dtdc"] is True
        failed = await client.call_tool(
            "check_serviceability", {"provider": "nope", "pincode": "110001"})
        assert failed.is_error and "Call list_providers" in text(failed)
