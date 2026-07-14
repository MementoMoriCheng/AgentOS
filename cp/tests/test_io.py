"""Week 7 T1: io 原语真实 HTTP 联网测试。

核心测试用 httpx.MockTransport(确定性,不依赖网络,不 flaky)。
另有一个真实网络测试(opt-in,无网时 skip)。"""
import socket

import httpx
import pytest

from cp.primitives.io import IoPrimitive
from cp.primitives.registry import PrimitiveContext
from cp.resource import Resource


def test_permission_key_uses_url():
    p = IoPrimitive()
    assert p.permission_key({"url": "https://example.com/x"}) == Resource(type="http_url", id="https://example.com/x")


def test_schema_has_method_and_url():
    s = IoPrimitive().schema()
    props = s["parameters"]["properties"]
    assert "method" in props and "url" in props
    assert s["parameters"]["required"] == ["method", "url"]


async def test_missing_url_returns_error():
    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "GET"})
    assert r.status == "error"
    assert "url" in r.error


def _mock_transport(handler):
    """返回一个 (transport, cleanup) 使 IoPrimitive 内部的 AsyncClient 用 mock。
    通过 monkeypatch httpx.AsyncClient 的 transport 参数。"""
    return httpx.MockTransport(handler)


async def test_get_via_mock_transport(monkeypatch):
    """用 MockTransport 测 GET 逻辑(确定性,不依赖网络)。"""
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert str(req.url) == "https://example.com/api?x=1"
        return httpx.Response(200, text="ok", headers={"x-test": "yes"})

    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = _mock_transport(handler)
        kw.pop("timeout", None)
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "GET", "url": "https://example.com/api?x=1"})
    assert r.status == "success"
    assert r.data["status"] == 200
    assert r.data["body"] == "ok"
    assert r.data["headers"]["x-test"] == "yes"


async def test_post_via_mock_transport(monkeypatch):
    """用 MockTransport 测 POST body 传递。"""
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["body"] = req.content
        return httpx.Response(201, text="created")

    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = _mock_transport(handler)
        kw.pop("timeout", None)
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "POST", "url": "https://example.com/create",
                                          "body": "payload-data"})
    assert r.status == "success"
    assert r.data["status"] == 201
    assert captured["method"] == "POST"
    assert b"payload-data" in captured["body"]


async def test_timeout_returns_error(monkeypatch):
    """超时返回 error,不崩。"""
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=req)

    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **kw):
        kw["transport"] = _mock_transport(handler)
        kw.pop("timeout", None)
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "GET", "url": "https://example.com/slow"})
    assert r.status == "error"
    assert "timeout" in r.error


async def test_real_network_get():
    """真实 GET(opt-in:无网时 skip,只断言拿到 HTTP 响应)。"""
    try:
        socket.gethostbyname("httpbin.org")
    except socket.gaierror:
        pytest.skip("no network")
    ctx = PrimitiveContext()
    r = await IoPrimitive().execute(ctx, {"method": "GET", "url": "https://httpbin.org/get?x=1"})
    # httpbin 有时不稳(503),只断言拿到响应(不是 error)
    assert r.status == "success"
    assert isinstance(r.data["status"], int)
