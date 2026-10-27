"""Owned, loopback-only audio.cpp CUDA server. Requests run on Studio's worker."""

import atexit
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from audio_catalog import AUDIO_WEIGHTS, NATIVE_MODELS, server_config
from engine_errors import MemoryPressure

log = logging.getLogger("h3.audio")


class AudioCppServer:
    def __init__(self, root, state_dir, *, port=8191, threads=8, timeout=1800):
        self.root, self.state_dir = Path(root), Path(state_dir)
        self.port, self.threads, self.timeout = port, threads, timeout
        self.process = None
        self.resident_model = None
        self.configured_ids = set()
        atexit.register(self.stop)

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def status(self):
        return {
            "running": self.running,
            "model": self.resident_model if self.running else None,
            "backend": "cuda",
            "version": "v0.9.3",
        }

    def _request(self, path, payload=None, *, timeout=None, binary=False):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                req, timeout=timeout or self.timeout
            ) as response:
                data = response.read()
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as exc:
            detail = (
                exc.read(8192)
                .decode(errors="replace")
                .replace(str(self.root), "$AUDIOCPP_DIR")
            )
            if any(
                s in detail.lower()
                for s in (
                    "out of memory",
                    "insufficient_memory",
                    "cuda allocation failed",
                )
            ):
                raise MemoryPressure(
                    "audio.cpp has insufficient GPU memory: " + detail
                ) from None
            raise RuntimeError(
                f"audio.cpp request failed ({exc.code}): {detail}"
            ) from None

    def start(self, model, check):
        if self.running and model in self.configured_ids:
            return
        self.stop()
        marker = self.root / "runtime" / ".studio-runtime.json"
        if not marker.is_file():
            raise RuntimeError(
                "audio.cpp runtime is not prepared; run deploy.sh models --only audio"
            )
        binary = self.root / "runtime" / json.loads(marker.read_text())["binary"]
        if not binary.is_file():
            raise RuntimeError(
                "audio.cpp server executable is missing; prepare the runtime again"
            )
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                raise RuntimeError(
                    "The configured audio.cpp port is occupied by another process"
                )
        config = server_config(self.root, self.port, self.threads)
        config["models"] = [m for m in config["models"] if Path(m["path"]).is_file()]
        self.configured_ids = {m["id"] for m in config["models"]}
        if model not in self.configured_ids:
            raise RuntimeError(
                "Selected audio model is not prepared; run deploy.sh models --only audio"
            )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.state_dir / "server.json"
        config_path.write_text(json.dumps(config, indent=2))
        env = dict(os.environ)
        libs = {str(binary.parent), str(binary.parent.parent / "lib")}
        libs.update(
            str(p)
            for p in (self.root / "runtime").rglob("*")
            if p.is_dir() and p.name in ("lib", "lib64")
        )
        libs.update(
            str(p)
            for p in Path(sys.prefix).glob("lib/python*/site-packages/nvidia/*/lib")
        )
        libs.update(
            p
            for p in ("/usr/local/cuda/lib64", "/usr/local/cuda-12.8/lib64")
            if Path(p).is_dir()
        )
        env["LD_LIBRARY_PATH"] = (
            ":".join(sorted(libs)) + ":" + env.get("LD_LIBRARY_PATH", "")
        )
        # The release carries assets/specs beside the executable or its parent.
        cwd = (
            binary.parent.parent
            if (binary.parent.parent / "assets").is_dir()
            else binary.parent
        )
        with (self.state_dir / "server.log").open("ab") as output:
            self.process = subprocess.Popen(
                [
                    str(binary),
                    "--config",
                    str(config_path),
                    "--backend",
                    "cuda",
                    "--no-ui",
                ],
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        try:
            end = time.monotonic() + 90
            while time.monotonic() < end:
                check()
                if not self.running:
                    raise RuntimeError(
                        "audio.cpp exited during startup; check its server log"
                    )
                try:
                    health = self._request("/health", timeout=1)
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    time.sleep(0.2)
                    continue
                if str(health.get("backend", "")).lower() != "cuda":
                    raise RuntimeError(
                        "audio.cpp did not start with the required CUDA backend"
                    )
                log.info(
                    "native CUDA server ready, %d configured models",
                    len(self.configured_ids),
                )
                return
            raise RuntimeError("audio.cpp startup timed out")
        except Exception:
            self.stop()
            raise

    def infer(self, model, path, payload, check, *, binary=False):
        family, weight, task = NATIVE_MODELS[model]
        if not (self.root / "models" / AUDIO_WEIGHTS[weight]["target"]).is_file():
            raise RuntimeError(
                "Selected audio model is not prepared; run deploy.sh models --only audio"
            )
        self.start(model, check)
        check()
        # Record before inference, including requests that fail partway through a load.
        self.resident_model = model
        try:
            result = self._request(path, payload, binary=binary)
            check()
            return result
        except Exception:
            self.stop()  # Native CUDA faults and canceled requests cannot poison the next job.
            check()
            raise

    def unload(self):
        if self.running and self.resident_model is not None:
            try:
                self._request("/v1/tasks/unload_all_models", {}, timeout=20)
            except Exception:
                self.stop()
                return
            self.resident_model = None
            log.info("audio.cpp weights unloaded; idle CUDA server retained")

    def request_stop(self):
        """Nonblocking cancellation from the HTTP thread; only signal our own child."""
        if self.running:
            process = self.process
            try:
                process.terminate()
            except ProcessLookupError:
                return

            # Native SIGTERM may wait for an in-flight CUDA request. Escalate
            # against this exact child so cancellation cannot wait indefinitely.
            def kill_if_needed():
                if process.poll() is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass

            timer = threading.Timer(2, kill_if_needed)
            timer.daemon = True
            timer.start()

    def stop(self):
        process = self.process
        self.request_stop()
        if process is not None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise MemoryPressure(
                        "The owned audio.cpp process could not stop; GPU recovery is required"
                    ) from None
        self.process = None
        self.resident_model = None
        self.configured_ids = set()
