"""Build Duru source/wheel artifacts and verify a dependency-free installation."""

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
import venv
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from release_checks.artifacts import unpack_sdist, wheel_payload
from release_checks.snapshot import compare_source, copy_source


def run(*arguments, cwd):
    subprocess.run([str(value) for value in arguments], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".verification/release"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="duru-release-") as directory:
        work = Path(directory)
        source, artifacts, rebuilt = (
            work / "source",
            work / "artifacts",
            work / "rebuilt",
        )
        copy_source(root, source)
        run(
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--wheel",
            "--outdir",
            artifacts,
            cwd=source,
        )
        wheel = next(artifacts.glob("*.whl"))
        sdist = next(artifacts.glob("*.tar.gz"))
        unpacked = unpack_sdist(sdist, work / "unpacked")
        run(sys.executable, "-m", "build", "--wheel", "--outdir", rebuilt, cwd=unpacked)
        version = tomllib.loads(
            (source / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
        original = wheel_payload(wheel, version)
        if not original or original != wheel_payload(
            next(rebuilt.glob("*.whl")), version
        ):
            raise ValueError(
                "Source wheel and sdist-rebuilt wheel package bytes differ"
            )
        compare_source(source, original)
        run(sys.executable, "-m", "twine", "check", "--strict", wheel, sdist, cwd=work)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        run(python, "-m", "pip", "install", "--no-deps", wheel, cwd=work)
        run(python, "-m", "pip", "check", cwd=work)
        run(python, "-I", root / "tools/release_checks/smoke.py", cwd=work)
        for artifact in (wheel, sdist):
            shutil.copy2(artifact, output / artifact.name)
        result = {
            "passed": True,
            "package_files": len(original),
            "framework_required": False,
            "source_bytes_checked": True,
            "sdist_rebuild_payload_equal": True,
            "sha256": {
                path.name: sha256(path.read_bytes()).hexdigest()
                for path in (wheel, sdist)
            },
        }
        (output / "checks.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"passed": True, "output": str(output)}))


if __name__ == "__main__":
    main()
