"""Release checks reject matching-but-incomplete wheels and false metadata."""

from zipfile import ZipFile

import pytest

from tools.release_checks.artifacts import wheel_payload
from tools.release_checks.snapshot import compare_source


def artifact(tmp_path, *, name="duru", version="0.1.0", private=False):
    source = tmp_path / "src/duru"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"VALUE = 1\n")
    (source / "README.md").write_bytes(b"Provider usage\n")
    wheel = tmp_path / "candidate.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("duru/__init__.py", b"VALUE = 1\n")
        archive.writestr("duru/README.md", b"Provider usage\n")
        archive.writestr(
            "duru-0.1.0.dist-info/licenses/LICENSE", b"BSD license fixture"
        )
        archive.writestr(
            "duru-0.1.0.dist-info/METADATA",
            f"Name: {name}\nVersion: {version}\nLicense-Expression: BSD-3-Clause\n",
        )
        if private:
            archive.writestr("duru/.runtime/credential.token", b"synthetic fixture")
    return wheel


def test_source_and_metadata_match(tmp_path):
    payload = wheel_payload(artifact(tmp_path), "0.1.0")
    compare_source(tmp_path, payload)
    assert len(payload) == 2


@pytest.mark.parametrize("change", [{"name": "another-project"}, {"version": "0.0.0"}])
def test_false_distribution_metadata_is_rejected(tmp_path, change):
    with pytest.raises(ValueError, match="metadata differs"):
        wheel_payload(artifact(tmp_path, **change), "0.1.0")


@pytest.mark.parametrize("change", ["omit-guide", "change-python"])
def test_matching_wheels_cannot_hide_source_drift(tmp_path, change):
    payload = wheel_payload(artifact(tmp_path), "0.1.0")
    if change == "omit-guide":
        payload.pop("duru/README.md")
    else:
        payload["duru/__init__.py"] = b"VALUE = 2\n"
    with pytest.raises(ValueError, match="source snapshot"):
        compare_source(tmp_path, payload)


def test_private_member_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="private distribution member"):
        wheel_payload(artifact(tmp_path, private=True), "0.1.0")
