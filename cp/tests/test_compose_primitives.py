from cp.compose import build_control_plane, make_primitive_context


async def test_compose_has_primitive_layer(fake_redis):
    cp = build_control_plane(fake_redis)
    assert "prim_registry" in cp
    assert "prim_executor" in cp
    names = set(cp["prim_registry"].names())
    assert names == {"exec", "read", "write", "llm", "io", "pub", "sub"}


async def test_compose_make_context(fake_redis):
    cp = build_control_plane(fake_redis)
    ctx = make_primitive_context(cp, session=None, sandbox_id="sbx")
    assert ctx.sandbox_id == "sbx"
    assert ctx.state is not None
