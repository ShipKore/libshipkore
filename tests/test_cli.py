"""The command line: tracking and read-only lookups, on the same facade as everything else."""

import json
import os
import subprocess
import sys

import pytest
import requests
import responses
from click.testing import CliRunner

from libshipkore import cli
from libshipkore.book.models import Address, Product
from libshipkore.client import Shipkore
from libshipkore.track.models.model import Checkpoint, Track

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
DELHIVERY = "https://track.delhivery.com"
with open(os.path.join(HERE, "fixtures", "delhivery.json")) as f:
    DLV = json.load(f)


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "providers": {"delhivery": {"credentials": {"api_token": "tok"}}},
        "storage": f"sqlite:///{tmp_path / 'kore.db'}",
    }))
    path.chmod(0o600)
    return str(path)


def run(*args, **kwargs):
    return CliRunner().invoke(cli.main, list(args), **kwargs)


def make_track(status="InTransit"):
    return Track(
        waybill="1234567890123", provider="delhivery", status=status,
        checkpoints=[Checkpoint(slug="delhivery", message="scan",
                                checkpoint_time="2026-01-02T03:04:05Z")],
    )


@pytest.fixture
def tracker(monkeypatch):
    calls = []
    monkeypatch.setattr("libshipkore.book.base.get_track_data",
                        lambda slug, waybill: calls.append((slug, waybill)) or make_track())
    return calls


# shape ---------------------------------------------------------------------

def test_a_bare_invocation_shows_the_commands_and_succeeds():
    # Click 8.0/8.1 exit 0 here and 8.2+ exit 2; the command now behaves the same on all of them
    result = run()
    assert result.exit_code == 0
    for command in ("providers", "track", "serviceability", "services", "rates", "orders", "order"):
        assert command in result.output


def test_help_lists_every_option_the_commands_take():
    assert run("--help").exit_code == 0
    assert "--config" in run("--help").output
    assert "--refresh" in run("track", "--help").output


def test_nothing_that_changes_a_provider_is_offered():
    for forbidden in ("create-order", "create_order", "cancel", "pickup", "ndr", "book"):
        assert not any(forbidden in name for name in cli.main.commands), forbidden


# providers -----------------------------------------------------------------

def test_providers_shows_what_each_one_can_do():
    result = run("providers")
    assert result.exit_code == 0
    providers = json.loads(result.output)
    assert providers["dtdc"] == ["track"]
    assert {"create_shipment", "label", "ndr_action", "track"} <= set(providers["delhivery"])
    assert len(providers) == 39


# tracking ------------------------------------------------------------------

def test_track_prints_the_standard_json(tracker):
    result = run("track", "--provider", "delhivery", "--waybill", "1234567890123")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "InTransit" and data["waybill"] == "1234567890123"
    assert data["checkpoints"][0]["checkpoint_time"] == "2026-01-02T03:04:05+00:00"  # the documented format
    assert tracker == [("delhivery", "1234567890123")]


def test_a_stored_result_is_reused_across_separate_runs_until_refreshed(tracker, config):
    args = ["--config", config, "track", "--provider", "delhivery", "--waybill", "1234567890123"]
    assert run(*args).exit_code == 0 and run(*args).exit_code == 0
    assert len(tracker) == 1  # the second run came from the SQLite file
    assert run(*args, "--refresh").exit_code == 0
    assert len(tracker) == 2


def test_without_a_config_nothing_is_kept_between_runs(tracker):
    args = ["track", "--provider", "delhivery", "--waybill", "1"]
    run(*args), run(*args)
    assert len(tracker) == 2


def test_the_config_can_come_from_the_environment(tracker, config):
    args = ["track", "--provider", "delhivery", "--waybill", "1"]
    for _ in range(2):
        assert run(*args, env={"LIBSHIPKORE_CONFIG": config}).exit_code == 0
    assert len(tracker) == 1


def test_a_mistyped_provider_gets_a_suggestion_and_no_traceback(tracker):
    result = run("track", "--provider", "delhivry", "--waybill", "1")
    assert result.exit_code == 1
    assert "Did you mean delhivery" in result.output and "Traceback" not in result.output


def test_tracker_failures_are_explained_not_dumped(monkeypatch):
    def broken(slug, waybill):
        raise KeyError("shipmentTrackingDetails")

    def offline(slug, waybill):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("libshipkore.book.base.get_track_data", broken)
    result = run("track", "--provider", "ekart", "--waybill", "1")
    assert result.exit_code == 1 and "may have changed" in result.output and "Traceback" not in result.output
    monkeypatch.setattr("libshipkore.book.base.get_track_data", offline)
    result = run("track", "--provider", "ekart", "--waybill", "1")
    assert result.exit_code == 1 and "could not reach ekart" in result.output


# lookups -------------------------------------------------------------------

@responses.activate
def test_serviceability(config):
    responses.add(responses.GET, DELHIVERY + "/c/api/pin-codes/json/", json=DLV["serviceability_ok"])
    result = run("--config", config, "serviceability", "--provider", "delhivery", "--pincode", "110001")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["serviceable"] is True
    assert responses.calls[0].request.headers["Authorization"] == "Token tok"


@responses.activate
def test_rates_sends_the_parcel_and_payment_mode(config):
    responses.add(responses.GET, DELHIVERY + "/api/kinko/v1/invoice/charges/.json", json=DLV["rates"])
    result = run("--config", config, "rates", "--provider", "delhivery", "--origin-pincode", "110001",
                 "--destination-pincode", "560001", "--weight-kg", "2", "--payment-mode", "COD")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["amount"] == 85.5
    assert "cgm=2000" in responses.calls[0].request.url and "pt=COD" in responses.calls[0].request.url


def test_rates_rejects_a_nonsense_weight_before_calling_anyone():
    result = run("rates", "--provider", "delhivery", "--origin-pincode", "1", "--destination-pincode", "2",
                 "--weight-kg", "0")
    assert result.exit_code == 2 and "weight-kg" in result.output


def test_services(config):
    result = run("--config", config, "services", "--provider", "delhivery")
    assert [s["name"] for s in json.loads(result.output)] == ["Express", "Surface"]
    unsupported = run("services", "--provider", "dtdc")
    assert unsupported.exit_code == 1 and "Not supported" in unsupported.output or "dtdc" in unsupported.output


def test_missing_credentials_say_what_is_missing():
    result = run("serviceability", "--provider", "delhivery", "--pincode", "110001")
    assert result.exit_code == 1 and "api_token" in result.output and "Traceback" not in result.output


# stored orders -------------------------------------------------------------

@pytest.fixture
def booked(config):
    with Shipkore.from_config(json.load(open(config))) as kore:
        kore.save_product(Product(sku="TEE", name="T-shirt", price=499, weight_kg=0.3))
        with responses.RequestsMock() as rsps:
            rsps.add(responses.POST, DELHIVERY + "/api/cmu/create.json", json=DLV["create_ok"])
            return kore.create_order(
                "delhivery", "ORD-1",
                Address(name="Asha", phone="9876543210", address="12 MG Road", pincode="560001",
                        city="Bengaluru", state="Karnataka"),
                "Main WH", items=[{"sku": "TEE", "quantity": 2}])


def test_orders_and_order_read_what_the_facade_stored(booked, config):
    listed = json.loads(run("--config", config, "orders").output)
    assert [o["order_id"] for o in listed] == ["ORD-1"]
    assert json.loads(run("--config", config, "orders", "--provider", "delhivery").output)[0]["waybill"] == "1234567890123"
    assert json.loads(run("--config", config, "orders", "--status", "Cancelled").output) == []
    one = json.loads(run("--config", config, "order", "ORD-1").output)
    assert one["status"] == "Booked" and one["description"] == "T-shirt x2"


def test_a_missing_order_is_a_message_not_a_crash(config):
    result = run("--config", config, "order", "ghost")
    assert result.exit_code == 1 and "no order 'ghost'" in result.output and "Traceback" not in result.output


def test_orders_validates_its_options(config):
    assert run("--config", config, "orders", "--status", "Bogus").exit_code == 2
    assert run("--config", config, "orders", "--limit", "0").exit_code == 2


# configuration -------------------------------------------------------------

def test_a_bad_config_is_reported_plainly(tmp_path):
    # `providers` never reads the config, so a bad path only matters to commands that need it
    assert run("--config", str(tmp_path / "nope.json"), "providers").exit_code == 0
    missing = run("--config", str(tmp_path / "nope.json"), "orders")
    assert missing.exit_code == 1 and "config file not found" in missing.output
    path = tmp_path / "bad.json"
    path.write_text('{"sandbx": true}')
    result = run("--config", str(path), "orders")
    assert result.exit_code == 1 and "unknown config keys" in result.output and "sandbx" in result.output
    path.write_text("{not json")
    assert "cannot read config file" in run("--config", str(path), "orders").output


def test_a_config_that_names_an_unset_variable_says_which(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"providers": {"delhivery": {"credentials": {"api_token": "${NOT_SET_ANYWHERE}"}}}}))
    result = run("--config", str(path), "orders", env={"NOT_SET_ANYWHERE": None})
    assert result.exit_code == 1 and "NOT_SET_ANYWHERE" in result.output


# the forms the README documents --------------------------------------------

def test_python_dash_m_works_and_prints_json():
    result = subprocess.run([sys.executable, "-m", "libshipkore.cli", "providers"], cwd=ROOT, text=True,
                            capture_output=True, timeout=120, env={**os.environ, "PYTHONPATH": ROOT})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["dtdc"] == ["track"]
    assert "pkg_resources" not in result.stderr
