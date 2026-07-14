from cp.ports import StatePort, MessageBusPort, SandboxPort, AuthPort, AuditPort


def test_ports_are_protocols():
    for p in [StatePort, MessageBusPort, SandboxPort, AuthPort, AuditPort]:
        assert hasattr(p, "_is_protocol"), f"{p.__name__} must be a Protocol"


def test_sandbox_port_has_create_exec_destroy():
    for m in ["create", "exec_action", "destroy"]:
        assert hasattr(SandboxPort, m), f"SandboxPort missing {m}"


def test_message_bus_port_has_publish_subscribe():
    for m in ["publish", "subscribe"]:
        assert hasattr(MessageBusPort, m), f"MessageBusPort missing {m}"


def test_state_port_has_get_save_delete():
    for m in ["get_session", "save_session", "delete_session"]:
        assert hasattr(StatePort, m), f"StatePort missing {m}"
