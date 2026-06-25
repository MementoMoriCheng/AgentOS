from agentos_runtime.kernel_client import KernelClient


class FakeStub:
    def __init__(self):
        self.calls = []

    def StartSession(self, req, **kw):
        self.calls.append(("start", req.policy_path, req.sanitization_path))
        class R:
            session_id = "sess-fake"
        return R()

    def CallTool(self, req, **kw):
        self.calls.append(("call", req.tool, req.params_json))
        class R:
            allowed = True
            errored = False
            message = ""
            result_json = '{"content":"hi"}'
        return R()


def test_start_and_call():
    client = KernelClient("dummy.sock")
    client._stub = FakeStub()  # 绕过真实 channel
    sid = client.start_session("p.yaml", "s.yaml")
    assert sid == "sess-fake"
    result = client.call_tool(sid, "fs_read", {"path": "x"})
    assert result["allowed"] is True
    assert result["result"] == {"content": "hi"}


def test_start_session_passes_both_paths():
    client = KernelClient("dummy.sock")
    fake = FakeStub()
    client._stub = fake
    client.start_session("policy.yaml", "sanitization.yaml")
    assert fake.calls[0] == ("start", "policy.yaml", "sanitization.yaml")


def test_call_tool_empty_params():
    client = KernelClient("dummy.sock")
    fake = FakeStub()
    client._stub = fake
    client.call_tool("s1", "fs_read", {})
    # 空字典应序列化成空 JSON 或空字符串，不报错
    assert fake.calls[0][0] == "call"


def test_call_tool_handles_denied():
    client = KernelClient("dummy.sock")

    class DenyStub:
        def CallTool(self, req, **kw):
            class R:
                allowed = False
                errored = False
                message = "permission denied"
                result_json = ""
            return R()

    client._stub = DenyStub()
    result = client.call_tool("s1", "fs_read", {"path": "/etc/shadow"})
    assert result["allowed"] is False
    assert result["message"] == "permission denied"
    assert result["result"] == {}
