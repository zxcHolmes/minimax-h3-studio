"""Safely install the pinned native CUDA runtime after a verified download."""

import json
import shutil
import tarfile

from audio_catalog import RUNTIME_NAME, RUNTIME_SHA256
from model_download import verify_checksum


def install_runtime(root):
    archive = root / "packages" / RUNTIME_NAME
    target = root / "runtime"
    marker = target / ".studio-runtime.json"
    if marker.exists():
        try:
            installed = json.loads(marker.read_text())
            executable = (target / installed["binary"]).resolve()
            if (
                installed.get("sha256") == RUNTIME_SHA256
                and executable.is_relative_to(target.resolve())
                and executable.is_file()
            ):
                return
        except (ValueError, KeyError):
            pass
    verify_checksum(archive, RUNTIME_SHA256)
    temp = root / "runtime.new"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    try:
        with tarfile.open(archive) as tar:
            # This pinned archive contains regular files/directories only. Reject
            # links and devices and copy members explicitly for Python 3.9 too.
            for member in tar.getmembers():
                dest = (temp / member.name).resolve()
                if not dest.is_relative_to(temp.resolve()):
                    raise ValueError(
                        "Runtime archive member escapes the installation directory"
                    )
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as inp, dest.open("wb") as output:
                        shutil.copyfileobj(inp, output)
                    dest.chmod(0o755 if member.mode & 0o111 else 0o644)
                else:
                    raise ValueError("Runtime archive links/devices are not permitted")
        binaries = list(temp.rglob("audiocpp_server"))
        if len(binaries) != 1:
            raise RuntimeError("runtime archive must contain one audiocpp_server")
        binary = binaries[0]
        binary.chmod(binary.stat().st_mode | 0o111)
        (temp / ".studio-runtime.json").write_text(
            json.dumps(
                {"sha256": RUNTIME_SHA256, "binary": str(binary.relative_to(temp))}
            )
        )
        old = root / "runtime.old"
        if old.exists():
            shutil.rmtree(old)
        if target.exists():
            target.rename(old)
        temp.rename(target)
        if old.exists():
            shutil.rmtree(old)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print("audio.cpp CUDA runtime installed", flush=True)
