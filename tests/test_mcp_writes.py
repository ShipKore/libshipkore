"""
Tests for the MCP write tools and the preview-then-confirm protocol.

A preview must change nothing (here: make no HTTP call at all, since no route
is registered), and a token must run only the exact arguments it was shown
for, once, before it expires.
"""

import json
import os

import anyio
import pytest
import responses

pytest.importorskip("mcp")

from mcp import StdioServerParameters  # noqa: E402
from mcp.client import Client  # noqa: E402
from mcp.types import ElicitResult  # noqa: E402

from libshipkore.book.models import Address, OrderStatus, Product  # noqa: E402
from libshipkore.client import Shipkore  # noqa: E402
from libshipkore.files import MemoryFileStore  # noqa: E402
from libshipkore.mcp_server.confirm import COLLECTION, PendingActions  # noqa: E402
from libshipkore.mcp_server.server import build_server  # noqa: E402
from libshipkore.storage import MemoryStorage  # noqa: E402

pytestmark = pytest.mark.anyio

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
DELHIVERY = "https://track.delhivery.com"
SHIPROCKET = "https://apiv2.shiprocket.in/v1/external"
CREATE = DELHIVERY + "/api/cmu/create.json"
with open(os.path.join(HERE, "fixtures", "delhivery.json")) as f:
    DLV = json.load(f)
with open(os.path.join(HERE, "fixtures", "shiprocket.json")) as f:
    SR = json.load(f)

PROVIDERS = {
    "delhivery": {"credentials": {"api_token": "tok"}},
    "shiprocket": {"credentials": {"email": "a@b.c", "password": "pw"}},
}
CONSIGNEE = {"name": "Asha", "phone": "9876543210", "address": "12 MG Road",
             "pincode": "560001", "city": "Bengaluru", "state": "Karnataka"}
ORDER = {"provider": "delhivery", "order_id": "ORD-1", "consignee": CONSIGNEE,
         "pickup_location": "Main WH", "items": [{"sku": "TEE", "quantity": 2}]}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def clock():
    from datetime import datetime, timezone
    return {"now": datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)}


@pytest.fixture
def kore():
    shipkore = Shipkore(providers=PROVIDERS, storage=MemoryStorage(), files=MemoryFileStore())
    shipkore.save_product(Product(sku="TEE", name="T-shirt", price=499, weight_kg=0.3))
    return shipkore


@pytest.fixture
def pending(kore, clock):
    return PendingActions(kore.storage, ttl=600, now=lambda: clock["now"])


@pytest.fixture
async def client(kore, pending):
    async with Client(build_server(kore, pending=pending)) as connected:
        yield connected


def text(result):
    return result.content[0].text


def data(result):
    """The structured result; the SDK wraps a union such as Preview | Order in {"result": ...}."""
    assert not result.is_error, text(result)
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


def approving(action="accept", approve=True, asked=None):
    async def callback(context, params):
        if asked is not None:
            asked.append(params.message)
        content = {"approve": approve} if action == "accept" else None
        return ElicitResult(action=action, content=content)
    return callback


async def preview(client, tool="create_order", **arguments):
    arguments = arguments or ORDER
    result = data(await client.call_tool(tool, arguments))
    assert result["status"] == "preview", result
    return result


def booked(kore, order_id="ORD-1"):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
        return kore.create_order(
            "delhivery", order_id, Address(**CONSIGNEE), "Main WH",
            items=[{"sku": "TEE", "quantity": 2}])


# the preview changes nothing -----------------------------------------------

async def test_a_preview_books_nothing_and_calls_no_provider(client, kore):
    with responses.RequestsMock() as rsps:  # no routes: any HTTP call would raise
        result = await preview(client)
        assert len(rsps.calls) == 0
    assert result["action"] == "create_order" and result["confirmation_token"]
    assert kore.list_orders() == []
    summary = result["summary"]
    assert summary["declared_value"] == 998 and summary["parcel"]["weight_kg"] == pytest.approx(0.6)
    assert summary["items"] == [{"sku": "TEE", "name": "T-shirt", "quantity": 2, "unit_price": 499}]
    assert summary["consignee"]["pincode"] == "560001" and summary["mode"] == "live"
    assert any("Live mode" in w for w in result["warnings"])
    assert "same arguments plus confirmation_token" in result["next_step"]


async def test_the_preview_warns_about_cash_on_delivery(client):
    result = await preview(client, **{**ORDER, "payment_mode": "COD", "cod_amount": 500})
    assert any("collect 500" in w for w in result["warnings"])
    assert any("differs from the declared value" in w for w in result["warnings"])
    assert "cash on delivery 500" in result["headline"]


async def test_a_sandbox_preview_says_so():
    kore = Shipkore(providers={"delhivery": {"credentials": {"api_token": "t"}, "sandbox": True}},
                    storage=MemoryStorage())
    kore.save_product(Product(sku="TEE", name="T", price=1, weight_kg=1))
    async with Client(build_server(kore)) as client:
        result = await preview(client)
    assert result["summary"]["mode"] == "sandbox"
    assert any("Sandbox mode" in w for w in result["warnings"])


# confirming ----------------------------------------------------------------

async def test_the_token_with_the_same_arguments_books_the_order(client, kore):
    token = (await preview(client))["confirmation_token"]
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
        order = data(await client.call_tool("create_order", {**ORDER, "confirmation_token": token}))
        assert len(rsps.calls) == 1
    assert order["status"] == "Booked" and order["waybill"] == "1234567890123"
    assert kore.get_order("ORD-1").status == OrderStatus.Booked


async def test_a_token_works_once(client):
    token = (await preview(client))["confirmation_token"]
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
        data(await client.call_tool("create_order", {**ORDER, "confirmation_token": token}))
        again = await client.call_tool("create_order", {**ORDER, "confirmation_token": token})
        assert len(rsps.calls) == 1
    assert again.is_error and "unknown, already used or expired" in text(again)


@pytest.mark.parametrize("change", [
    {"cod_amount": 1}, {"order_id": "ORD-2"}, {"payment_mode": "COD"},
    {"consignee": {**CONSIGNEE, "pincode": "110001"}},
    {"items": [{"sku": "TEE", "quantity": 3}]}, {"provider_options": {}} and {"description": "x"},
])
async def test_changed_arguments_do_not_run_and_do_not_burn_the_token(client, kore, change):
    token = (await preview(client))["confirmation_token"]
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
        tampered = await client.call_tool(
            "create_order", {**ORDER, **change, "confirmation_token": token})
        assert tampered.is_error and "differ from the preview" in text(tampered)
        assert len(rsps.calls) == 0 and kore.list_orders() == []
        # the honest repeat still works: a wrong guess does not cost the user a new preview
        ok = await client.call_tool("create_order", {**ORDER, "confirmation_token": token})
        assert not ok.is_error and len(rsps.calls) == 1


async def test_a_token_is_for_one_action_only(client):
    token = (await preview(client))["confirmation_token"]
    result = await client.call_tool("cancel_order", {"order_id": "ORD-1", "confirmation_token": token})
    assert result.is_error and "issued for create_order, not cancel_order" in text(result)


async def test_an_unknown_token_is_rejected(client):
    result = await client.call_tool("create_order", {**ORDER, "confirmation_token": "made-up"})
    assert result.is_error and "unknown, already used or expired" in text(result)
    assert "without a token" in text(result)


async def test_a_token_expires(client, clock):
    token = (await preview(client))["confirmation_token"]
    clock["now"] += __import__("datetime").timedelta(seconds=601)
    with responses.RequestsMock() as rsps:
        result = await client.call_tool("create_order", {**ORDER, "confirmation_token": token})
        assert len(rsps.calls) == 0
    assert result.is_error and "expired" in text(result)


async def test_a_token_is_still_valid_just_before_it_expires(client, clock):
    token = (await preview(client))["confirmation_token"]
    clock["now"] += __import__("datetime").timedelta(seconds=599)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
        assert not (await client.call_tool(
            "create_order", {**ORDER, "confirmation_token": token})).is_error


async def test_simultaneous_confirmations_book_exactly_once(client, kore):
    token = (await preview(client))["confirmation_token"]
    results = []

    async def confirm():
        results.append(await client.call_tool(
            "create_order", {**ORDER, "confirmation_token": token}))

    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
        async with anyio.create_task_group() as tasks:
            for _ in range(4):
                tasks.start_soon(confirm)
        assert len(rsps.calls) == 1
    assert sum(not r.is_error for r in results) == 1
    assert len(kore.list_orders()) == 1


async def test_tokens_are_stored_hashed_and_expired_ones_are_purged(client, kore, clock):
    first = (await preview(client))["confirmation_token"]
    stored = json.dumps(kore.storage.list(COLLECTION))
    assert first not in stored and "arguments_hash" in stored
    clock["now"] += __import__("datetime").timedelta(seconds=700)
    await preview(client, **{**ORDER, "order_id": "ORD-2"})
    assert len(kore.storage.list(COLLECTION)) == 1


# a preview that cannot succeed says so instead of issuing a token ---------

async def test_problems_are_reported_at_preview_time(client, kore):
    booked(kore)
    cases = [
        ({**ORDER}, "already Booked"),
        ({**ORDER, "order_id": "N", "items": [{"sku": "NOPE"}]}, "no product with sku 'NOPE'"),
        ({**ORDER, "order_id": "N", "items": None}, "give a parcel"),
        ({**ORDER, "order_id": "N", "provider_options": {"courier_id": 5}}, "takes no provider options"),
        ({**ORDER, "order_id": "N", "provider": "shiprocket"}, "shiprocket requires consignee.email"),
        ({**ORDER, "order_id": "N", "provider": "delhivry"}, "Did you mean delhivery"),
    ]
    for arguments, message in cases:
        result = await client.call_tool("create_order", arguments)
        assert result.is_error and message in text(result), (message, text(result))
    assert kore.storage.list(COLLECTION) == []


# cancel --------------------------------------------------------------------

async def test_cancel_previews_the_order_then_cancels_it(client, kore):
    booked(kore)
    result = await preview(client, "cancel_order", order_id="ORD-1")
    assert result["summary"]["waybill"] == "1234567890123"
    assert any("may refuse" in w for w in result["warnings"])
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/api/p/edit", json=DLV["cancel_ok"])
        order = data(await client.call_tool(
            "cancel_order", {"order_id": "ORD-1", "confirmation_token": result["confirmation_token"]}))
    assert order["status"] == "Cancelled"


async def test_cancelling_a_moving_shipment_warns_it_may_return_to_sender(client, kore):
    booked(kore)
    order = kore.get_order("ORD-1")
    order.delivery_status = "InTransit"
    kore._save_order(order)
    result = await preview(client, "cancel_order", order_id="ORD-1")
    assert any("send it back to the sender" in w for w in result["warnings"])


async def test_a_refused_cancel_is_an_error_after_confirmation(client, kore):
    booked(kore)
    token = (await preview(client, "cancel_order", order_id="ORD-1"))["confirmation_token"]
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/api/p/edit", json=DLV["cancel_rejected"])
        result = await client.call_tool(
            "cancel_order", {"order_id": "ORD-1", "confirmation_token": token})
    assert result.is_error and "picked up" in text(result)
    assert kore.get_order("ORD-1").status == OrderStatus.Booked


async def test_cancelling_what_is_not_booked_is_refused_at_preview(client, kore):
    result = await client.call_tool("cancel_order", {"order_id": "ghost"})
    assert result.is_error and "no order 'ghost'" in text(result)
    booked(kore)
    token = (await preview(client, "cancel_order", order_id="ORD-1"))["confirmation_token"]
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/api/p/edit", json=DLV["cancel_ok"])
        await client.call_tool("cancel_order", {"order_id": "ORD-1", "confirmation_token": token})
    again = await client.call_tool("cancel_order", {"order_id": "ORD-1"})
    assert again.is_error and "Cancelled, not booked" in text(again)


async def test_an_asynchronous_cancel_leaves_the_order_pending(kore):
    kore.providers["shiprocket"]["sandbox"] = False
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, SHIPROCKET + "/auth/login", json=SR["login"])
        rsps.add(responses.POST, SHIPROCKET + "/orders/create/adhoc", json=SR["create_order"])
        rsps.add(responses.POST, SHIPROCKET + "/courier/assign/awb", json=SR["assign_awb"])
        rsps.add(responses.POST, SHIPROCKET + "/orders/cancel/shipment/awbs", json=SR["cancel_ok"])
        kore.create_order(
            "shiprocket", "SR-1", Address(**CONSIGNEE, email="a@b.c"), "Primary",
            parcel={"weight_kg": 1, "length_cm": 10, "breadth_cm": 10, "height_cm": 5})
        async with Client(build_server(kore)) as client:
            result = await preview(client, "cancel_order", order_id="SR-1")
            assert any("CancelPending" in w for w in result["warnings"])
            order = data(await client.call_tool("cancel_order", {
                "order_id": "SR-1", "confirmation_token": result["confirmation_token"]}))
    assert order["status"] == "CancelPending"


# pickup and NDR ------------------------------------------------------------

async def test_pickup_preview_then_confirm(client, kore):
    booked(kore)
    arguments = {"order_id": "ORD-1", "pickup_date": "2026-11-03", "pickup_time": "14:30:00"}
    result = await preview(client, "schedule_pickup", **arguments)
    assert result["summary"]["pickup_location"] == "Main WH"
    assert any("per warehouse" in w for w in result["warnings"])
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/fm/request/new/", json=DLV["pickup_ok"])
        pickup = data(await client.call_tool(
            "schedule_pickup", {**arguments, "confirmation_token": result["confirmation_token"]}))
    assert pickup["pickup_id"] == "118775" and pickup["center"] == "Mumbai MIDC"
    assert kore.get_order("ORD-1").pickup.pickup_id == "118775"


async def test_a_pickup_missing_what_the_provider_needs_is_caught_at_preview(client, kore):
    booked(kore)
    result = await client.call_tool(
        "schedule_pickup", {"order_id": "ORD-1", "pickup_date": "2026-11-03"})
    assert result.is_error and "pickup_time" in text(result)
    assert kore.storage.list(COLLECTION) == []


async def test_a_pickup_for_a_cancelled_order_is_refused(client, kore):
    booked(kore)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/api/p/edit", json=DLV["cancel_ok"])
        kore.cancel_order("ORD-1")
    result = await client.call_tool("schedule_pickup", {
        "order_id": "ORD-1", "pickup_date": "2026-11-03", "pickup_time": "10:00:00"})
    assert result.is_error and "Cancelled, not booked" in text(result)


async def test_ndr_action_then_status(client, kore):
    booked(kore)
    result = await preview(client, "ndr_action", order_id="ORD-1", action="Reattempt")
    assert any("9 PM" in w for w in result["warnings"])
    upl = DLV["ndr_accepted"]["request_id"]
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, DELHIVERY + "/api/p/update", json=DLV["ndr_accepted"])
        done = data(await client.call_tool("ndr_action", {
            "order_id": "ORD-1", "action": "Reattempt",
            "confirmation_token": result["confirmation_token"]}))
        assert done["status"] == "Pending" and done["request_id"] == upl
        rsps.add(responses.GET, DELHIVERY + "/api/cmu/get_bulk_upl/" + upl,
                 json=DLV["ndr_status_partial"])
        status = data(await client.call_tool("ndr_status", {"order_id": "ORD-1"}))
    assert status["status"] == "Failed" and status["succeeded"] == ["1234567890123"]
    assert status["failed"] == {"999": "Package in incorrect status"}


async def test_an_ndr_action_the_provider_lacks_is_caught_at_preview(client, kore):
    booked(kore)
    result = await client.call_tool("ndr_action", {"order_id": "ORD-1", "action": "Defer"})
    assert result.is_error and "Not supported" in text(result) and "delhivery supports" in text(result)
    assert kore.storage.list(COLLECTION) == []


async def test_ndr_status_without_a_request_says_so(client, kore):
    booked(kore)
    result = await client.call_tool("ndr_status", {"order_id": "ORD-1"})
    assert result.is_error and "no NDR request" in text(result)


# asking the person directly ------------------------------------------------
# The SDK lets a server ask mid-call only on protocol 2025-11-25 and earlier;
# on 2026-07-28 it raises NoBackChannelError and we fall back to the token.

async def test_the_user_is_asked_with_the_previewed_headline(kore, pending):
    asked = []
    async with Client(build_server(kore, pending=pending), mode="legacy",
                      elicitation_callback=approving(asked=asked)) as client:
        result = await preview(client)
        with responses.RequestsMock() as rsps:
            rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
            order = data(await client.call_tool(
                "create_order", {**ORDER, "confirmation_token": result["confirmation_token"]}))
    assert order["status"] == "Booked"
    assert asked == [result["headline"]] and "ORD-1" in asked[0]
    assert len(asked) == 1  # the preview itself asks nothing


@pytest.mark.parametrize("action, approve", [
    ("decline", True), ("cancel", True), ("accept", False)])
async def test_a_user_who_says_no_stops_the_action_and_burns_the_token(kore, pending, action, approve):
    async with Client(build_server(kore, pending=pending), mode="legacy",
                      elicitation_callback=approving(action, approve)) as client:
        token = (await preview(client))["confirmation_token"]
        with responses.RequestsMock() as rsps:
            declined = await client.call_tool(
                "create_order", {**ORDER, "confirmation_token": token})
            assert len(rsps.calls) == 0
        assert declined.is_error and "user declined" in text(declined)
        assert kore.list_orders() == []
        retry = await client.call_tool("create_order", {**ORDER, "confirmation_token": token})
        assert retry.is_error and "unknown, already used or expired" in text(retry)


async def test_on_the_newest_protocol_the_token_alone_gates_the_action(kore, pending):
    """The client could answer, but the connection cannot carry the question."""
    asked = []
    async with Client(build_server(kore, pending=pending),
                      elicitation_callback=approving("decline", asked=asked)) as client:
        assert client.protocol_version == "2026-07-28"
        token = (await preview(client))["confirmation_token"]
        with responses.RequestsMock() as rsps:
            rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
            order = data(await client.call_tool(
                "create_order", {**ORDER, "confirmation_token": token}))
    assert order["status"] == "Booked" and asked == []


async def test_a_wrong_token_still_blocks_before_the_user_is_asked(kore, pending):
    asked = []
    async with Client(build_server(kore, pending=pending), mode="legacy",
                      elicitation_callback=approving(asked=asked)) as client:
        result = await client.call_tool("create_order", {**ORDER, "confirmation_token": "nope"})
    assert result.is_error and asked == []


async def test_elicitation_can_be_switched_off(kore, pending):
    asked = []
    async with Client(build_server(kore, pending=pending, elicit=False), mode="legacy",
                      elicitation_callback=approving("decline", asked=asked)) as client:
        token = (await preview(client))["confirmation_token"]
        with responses.RequestsMock() as rsps:
            rsps.add(responses.POST, CREATE, json=DLV["create_ok"])
            order = data(await client.call_tool(
                "create_order", {**ORDER, "confirmation_token": token}))
    assert order["status"] == "Booked" and asked == []


# changes that need no token ------------------------------------------------

async def test_get_label_copies_the_pdf_to_the_file_store(client, kore):
    booked(kore)
    link = DLV["label_ok"]["packages"][0]["pdf_download_link"]
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, DELHIVERY + "/api/p/packing_slip", json=DLV["label_ok"])
        rsps.add(responses.GET, link, body=b"%PDF-1.4")
        label = data(await client.call_tool("get_label", {"order_id": "ORD-1", "size": "4R"}))
    assert label["storage_key"] == "labels/delhivery/1234567890123.pdf"
    assert label["url"].startswith("memory://") and "content" not in label
    assert kore.files.get(label["storage_key"]) == b"%PDF-1.4"
    bad = await client.call_tool("get_label", {"order_id": "ORD-1", "size": "A5"})
    assert bad.is_error


async def test_the_catalog_will_not_be_overwritten_by_accident(client, kore):
    product = {"sku": "CAP", "name": "Cap", "price": 199, "weight_kg": 0.1}
    assert data(await client.call_tool("save_product", {"product": product}))["sku"] == "CAP"
    clash = await client.call_tool("save_product", {"product": {**product, "price": 1}})
    assert clash.is_error and "overwrite=true" in text(clash)
    assert kore.get_product("CAP").price == 199
    replaced = data(await client.call_tool(
        "save_product", {"product": {**product, "price": 1}, "overwrite": True}))
    assert replaced["price"] == 1
    assert data(await client.call_tool("delete_product", {"sku": "CAP"})) == {
        "sku": "CAP", "deleted": True}
    assert data(await client.call_tool("delete_product", {"sku": "CAP"}))["deleted"] is False


async def test_a_deleted_product_does_not_disturb_a_booked_order(client, kore):
    booked(kore)
    await client.call_tool("delete_product", {"sku": "TEE"})
    assert kore.get_order("ORD-1").description == "T-shirt x2"


# the real process ----------------------------------------------------------

async def test_the_two_step_protocol_over_a_real_stdio_process():
    params = StdioServerParameters(
        command=os.sys.executable, args=["-m", "libshipkore.mcp_server"],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT},
    )
    async with Client(params) as client:
        assert (await client.call_tool("save_product", {
            "product": {"sku": "TEE", "name": "T", "price": 10, "weight_kg": 1}})).is_error is False
        first = data(await client.call_tool("create_order", ORDER))
        assert first["status"] == "preview" and first["confirmation_token"]
        wrong = await client.call_tool(
            "create_order", {**ORDER, "cod_amount": 5, "confirmation_token": first["confirmation_token"]})
        assert wrong.is_error and "differ from the preview" in text(wrong)
