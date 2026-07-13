from cp.eventbus.bus import Event, InProcess


def test_subscribe_receives_published_event():
    bus = InProcess()
    received = []
    bus.subscribe(lambda e: received.append(e))
    bus.publish(Event(type="tool.called", session_id="s1"))
    assert len(received) == 1
    assert received[0].type == "tool.called"
    assert received[0].timestamp > 0  # publish 填充


def test_unsubscribe_stops_delivery():
    bus = InProcess()
    received = []
    unsub = bus.subscribe(lambda e: received.append(e))
    bus.publish(Event(type="x"))
    unsub()
    bus.publish(Event(type="y"))
    assert len(received) == 1


def test_handler_exception_does_not_crash_publish():
    bus = InProcess()
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    sink = []
    bus.subscribe(lambda e: sink.append(e))
    bus.publish(Event(type="x"))  # 不抛
    assert len(sink) == 1
