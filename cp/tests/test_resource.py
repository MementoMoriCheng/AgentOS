from cp.resource import Resource


def test_resource_holds_type_and_id():
    r = Resource(type="path", id="examples/workspace/sales.csv")
    assert r.type == "path"
    assert r.id == "examples/workspace/sales.csv"


def test_resource_is_frozen():
    import dataclasses
    r = Resource(type="path", id="x")
    assert dataclasses.is_dataclass(r)
    try:
        r.id = "y"
        assert False, "should be frozen"
    except dataclasses.FrozenInstanceError:
        pass
