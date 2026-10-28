"""
Tests for the local HTTP transport. The server tests start the real
libshipkore-mcp process and talk to it over a socket.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("mcp")

import httpx2  # noqa: E402
from mcp.client import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from libshipkore.common.exceptions import ConfigError  # noqa: E402
from libshipkore.mcp_server.http import (  # noqa: E402
    BearerToken,
    require_loopback,
    resolve_token,
    security_settings,
)

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
TOKEN = "t" * 32
INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "test", "version": "1"}},
}
JSON_HEADERS = {"Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"}

# the guards ----------------------------------------------------------------


@pytest.mark.parametrize("host", [
    "127.0.0.1", "127.0.0.2", "::1", "localhost", "LOCALHOST", "::ffff:127.0.0.1"])
def test_loopback_addresses_are_accepted(host):
    assert require_loopback(host) == host


@pytest.mark.parametrize("host", [
    "0.0.0.0", "::", "192.168.1.5", "10.0.0.1", "8.8.8.8", "example.com", "",
    "localhost.evil.com", "127.0.0.1.evil.com", "::ffff:192.168.1.1", "not an address"])
def test_everything_else_is_refused(host):
    with pytest.raises(ConfigError, match="local-only"):
        require_loopback(host)


def test_a_token_comes_from_the_environment_or_is_generated():
    assert resolve_token({"LIBSHIPKORE_MCP_TOKEN": TOKEN}) == (TOKEN, False)
    first, generated = resolve_token({})
    second, _ = resolve_token({})
    assert generated and len(first) >= 32 and first != second
    assert resolve_token({"LIBSHIPKORE_MCP_TOKEN": ""})[1] is True  # empty is not a token
    assert resolve_token({}, no_auth=True) == (None, False)
    assert resolve_token({"OTHER": TOKEN}, env_name="OTHER") == (TOKEN, False)


def test_a_weak_token_is_refused():
    with pytest.raises(ConfigError, match="too short") as error:
        resolve_token({"LIBSHIPKORE_MCP_TOKEN": "hunter2"})
    assert "hunter2" not in str(error.value)  # a secret is never echoed back


def test_host_and_origin_checks_name_this_port_only():
    settings = security_settings(8765)
    assert settings.enable_dns_rebinding_protection
    assert "127.0.0.1:8765" in settings.allowed_hosts and "localhost:8765" in settings.allowed_hosts
    assert "http://localhost:8765" in settings.allowed_origins
    assert not any(h.endswith(":*") for h in settings.allowed_hosts)
    assert "evil.example:8765" not in settings.allowed_hosts


async def call(app, authorization=None, scope_type="http"):
    headers = [(b"authorization", authorization.encode())] if authorization else []
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app({"type": scope_type, "method": "POST", "path": "/mcp", "headers": headers,
               "query_string": b"", "raw_path": b"/mcp"}, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], dict(start["headers"])


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_the_token_middleware():
    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    guarded = BearerToken(ok, TOKEN)
    assert (await call(guarded, f"Bearer {TOKEN}"))[0] == 200
    assert (await call(guarded, f"bearer {TOKEN}"))[0] == 200  # the scheme is case-insensitive
    for bad in (None, "", "Bearer", f"Bearer {TOKEN}x", f"Bearer {TOKEN[:-1]}",
                f"Basic {TOKEN}", f"Token {TOKEN}", TOKEN):
        status, headers = await call(guarded, bad)
        assert status == 401 and headers[b"www-authenticate"] == b"Bearer", bad


@pytest.mark.anyio
async def test_the_middleware_lets_lifespan_events_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])
        await send({"type": "http.response.start", "status": 200, "headers": []})

    await call(BearerToken(app, TOKEN), scope_type="lifespan")
    assert seen == ["lifespan"]  # starting and stopping the server needs no token


# the process ---------------------------------------------------------------


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Server:
    """libshipkore-mcp --transport http as a real subprocess."""

    def __init__(self, *args, token=TOKEN):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        env = {k: v for k, v in os.environ.items() if k != "LIBSHIPKORE_MCP_TOKEN"}
        env.update(PYTHONPATH=ROOT, PYTHONUNBUFFERED="1")
        if token:
            env["LIBSHIPKORE_MCP_TOKEN"] = token
        self.process = subprocess.Popen(
            [sys.executable, "-m", "libshipkore.mcp_server", "--transport", "http",
             "--port", str(self.port), *args],
            cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.lines = []
        threading.Thread(target=self._read, daemon=True).start()
        self._wait_until_listening()

    def _read(self):
        for line in self.process.stdout:
            self.lines.append(line.rstrip())

    @property
    def log(self):
        return "\n".join(self.lines)

    def _wait_until_listening(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(f"server exited early:\n{self.log}")
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        raise AssertionError(f"server never listened:\n{self.log}")

    def wait_for(self, text, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for line in self.lines:
                if text in line:
                    return line
            time.sleep(0.05)
        raise AssertionError(f"never logged {text!r}:\n{self.log}")

    def stop(self):
        self.process.terminate()
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()


@pytest.fixture
def start():
    started = []

    def factory(*args, **kwargs):
        started.append(Server(*args, **kwargs))
        return started[-1]

    yield factory
    for server in started:
        server.stop()


def authorised(token=TOKEN, **headers):
    return httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}", **headers})


async def post(server, headers=None, token=TOKEN):
    async with httpx2.AsyncClient() as http:
        merged = {**JSON_HEADERS, **({"Authorization": f"Bearer {token}"} if token else {}),
                  **(headers or {})}
        return await http.post(server.url, headers=merged, content=json.dumps(INITIALIZE))


@pytest.mark.anyio
async def test_an_agent_can_use_the_server_over_http(start):
    server = start()
    async with Client(streamable_http_client(server.url, http_client=authorised())) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {"list_providers", "create_order", "cancel_order", "get_rates"} <= tools
        providers = (await client.call_tool("list_providers", {})).structured_content["result"]
        assert any(p["slug"] == "delhivery" for p in providers)
        await client.call_tool("save_product", {"product": {
            "sku": "TEE", "name": "T", "price": 10, "weight_kg": 1}})
        order = {"provider": "delhivery", "order_id": "ORD-1", "items": [{"sku": "TEE"}],
                 "consignee": {"name": "A", "phone": "9", "address": "x", "pincode": "560001"},
                 "pickup_location": "WH"}
        first = (await client.call_tool("create_order", order)).structured_content["result"]
        assert first["status"] == "preview"  # the two-step protocol holds over HTTP too
        wrong = await client.call_tool(
            "create_order", {**order, "cod_amount": 9, "confirmation_token": first["confirmation_token"]})
        assert wrong.is_error and "differ from the preview" in wrong.content[0].text


@pytest.mark.anyio
async def test_requests_without_the_right_token_are_refused(start):
    server = start()
    for token in (None, "wrong-token-wrong-token-wrong", TOKEN[:-1]):
        response = await post(server, token=token)
        assert response.status_code == 401, token
    assert (await post(server)).status_code == 200


@pytest.mark.anyio
async def test_a_web_page_cannot_reach_it_through_a_rebound_name(start):
    server = start()
    foreign_host = await post(server, {"Host": f"evil.example:{server.port}"})
    assert foreign_host.status_code == 421
    wrong_port = await post(server, {"Host": "127.0.0.1:1"})
    assert wrong_port.status_code == 421
    foreign_origin = await post(server, {"Origin": "http://evil.example"})
    assert foreign_origin.status_code == 403
    assert (await post(server, {"Origin": "http://evil.example:8765"})).status_code == 403
    # the legitimate spellings still work
    assert (await post(server, {"Host": f"localhost:{server.port}"})).status_code == 200
    assert (await post(server, {"Origin": f"http://localhost:{server.port}"})).status_code == 200


@pytest.mark.anyio
async def test_a_generated_token_is_logged_and_required(start):
    server = start(token=None)
    line = server.wait_for("Bearer ")
    generated = line.split("Bearer ")[1].strip()
    assert len(generated) >= 32
    assert (await post(server, token=None)).status_code == 401
    assert (await post(server, token=generated)).status_code == 200


@pytest.mark.anyio
async def test_a_token_from_the_environment_is_never_logged(start):
    server = start()
    server.wait_for("listening on")
    assert TOKEN not in server.log
    assert "$LIBSHIPKORE_MCP_TOKEN" in server.log


@pytest.mark.anyio
async def test_no_auth_must_be_asked_for_and_is_loudly_warned_about(start):
    server = start("--no-auth", token=None)
    assert "authentication is OFF" in server.wait_for("authentication is OFF")
    assert (await post(server, token=None)).status_code == 200


def run_cli(*args, env=None):
    base = {k: v for k, v in os.environ.items() if k != "LIBSHIPKORE_MCP_TOKEN"}
    base.update(PYTHONPATH=ROOT, **(env or {}))
    return subprocess.run(
        [sys.executable, "-m", "libshipkore.mcp_server", *args],
        cwd=ROOT, env=base, text=True, capture_output=True, timeout=60,
    )


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "example.com"])
def test_the_server_will_not_start_on_a_reachable_address(host):
    result = run_cli("--transport", "http", "--host", host, "--port", str(free_port()))
    assert result.returncode != 0 and "local-only" in result.stderr


def test_a_bad_port_or_weak_token_stops_startup():
    bad_port = run_cli("--transport", "http", "--port", "70000")
    assert bad_port.returncode != 0 and "--port must be between" in bad_port.stderr
    weak = run_cli("--transport", "http", "--port", str(free_port()),
                   env={"LIBSHIPKORE_MCP_TOKEN": "hunter2"})
    assert weak.returncode != 0 and "too short" in weak.stderr and "hunter2" not in weak.stderr


def test_http_options_on_stdio_are_called_out():
    # stdio waits for a client on stdin; closing it ends the process at once
    result = subprocess.run(
        [sys.executable, "-m", "libshipkore.mcp_server", "--no-auth"],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT}, text=True,
        input="", capture_output=True, timeout=60,
    )
    assert "only apply to --transport http" in result.stderr
