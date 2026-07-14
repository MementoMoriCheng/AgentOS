from cp.eventbus.bus import Event, InProcess


async def test_subscribe_receives_published_event():
    bus = InProcess()
    received = []
    async def handler(e):
        received.append(e)
    bus.subscribe(handler)
    await bus.publish(Event(type="tool.called", session_id="s1"))
    assert len(received) == 1
    assert received[0].type == "tool.called"
    assert received[0].timestamp > 0


async def test_unsubscribe_stops_delivery():
    bus = InProcess()
    received = []
    async def handler(e):
        received.append(e)
    unsub = bus.subscribe(handler)
    await bus.publish(Event(type="x"))
    unsub()
    await bus.publish(Event(type="y"))
    assert len(received) == 1


async def test_handler_exception_does_not_crash_publish():
    bus = InProcess()
    async def boom(e):
        raise RuntimeError("boom")
    sink = []
    async def sink_handler(e):
        sink.append(e)
    bus.subscribe(boom)
    bus.subscribe(sink_handler)
    await bus.publish(Event(type="x"))
    assert len(sink) == 1
