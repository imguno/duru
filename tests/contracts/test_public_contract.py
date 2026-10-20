import io

import pytest

from duru import (
    NotFound,
    Provider,
    Registry,
    ResourceInfo,
    UnsupportedOperation,
    capabilities,
)


class OpaqueProvider(Provider):
    @property
    def identity(self):
        return "opaque-instance"

    def stat(self, uri):
        return ResourceInfo(uri, "A display name unrelated to the URI")

    def open(self, uri, *, expected_revision=None):
        return io.BytesIO(b"independent implementation")


def test_contract_has_no_name_or_path_inference():
    provider = OpaqueProvider()
    uri = "opaque:nonhierarchical-identifier"
    registry = Registry()
    registry.register("OPAQUE", provider)
    selected = registry.resolve(uri)
    assert selected is provider
    assert selected.stat(uri).name == "A display name unrelated to the URI"
    with selected.open(uri) as stream:
        assert stream.read() == b"independent implementation"
    assert stream.closed
    assert capabilities(provider) == {"stat", "read"}


def test_registry_is_explicit_and_does_not_replace_registration():
    registry = Registry()
    with pytest.raises(UnsupportedOperation):
        registry.resolve("missing://resource")
    registry.register("opaque", OpaqueProvider())
    with pytest.raises(ValueError):
        registry.register("opaque", OpaqueProvider())
    with pytest.raises(ValueError):
        registry.register("bad/scheme", OpaqueProvider())


def test_required_methods_and_common_errors():
    with pytest.raises(TypeError):
        Provider()
    assert isinstance(NotFound("missing"), FileNotFoundError)
    with pytest.raises(ValueError):
        ResourceInfo("opaque:id", "name", kind="unknown")
