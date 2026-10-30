"""Owned, loopback-only Strata LLM server. Batches run on Studio's worker; requests inside a batch run concurrently."""

import atexit
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from engine_errors import MemoryPressure

log = logging.getLogger("h3.llm")


class StrataServer:
    def __init__(self, root, config, state_dir, *, port=8192, parallel=8, timeout=1800):
        self.root, self.config, self.state_dir = Path(root), Path(config), Path(state_dir)
        self.port, self.parallel, self.timeout = port, parallel, timeout
        self.process = None
        atexit.register(self.stop)

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def model(self):
        try:
            return json.loads(self.config.read_text()).get("model_name") or self.config.stem
        except (OSError, ValueError):
            return self.config.stem

    @property
    def status(self):
        return {"running": self.running, "model": self.model, "parallel": self.parallel, "runtime": "strata"}

    def _request(self, path, payload=None, *, timeout=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read(8192).decode(errors="replace")
            if "out of memory" in detail.lower():
                raise MemoryPressure("Strata has insufficient GPU memory: " + detail) from None
            raise RuntimeError(f"Strata request failed ({exc.code}): {detail}") from None

    def start(self, check):
        if self.running:
            return
        self.stop()
        python, script = self.root / ".venv" / "bin" / "python", self.root / "serve" / "server.py"
        if not python.is_file() or not script.is_file() or not self.config.is_file():
            raise RuntimeError("Strata is not prepared; check H3_STRATA_DIR and H3_STRATA_CONFIG")
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                raise RuntimeError("The configured Strata port is occupied by another process")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "server.log").open("ab") as output:
            self.process = subprocess.Popen(
                [str(python), str(script), "--engine", "strata", "--config", str(self.config),
                 "--host", "127.0.0.1", "--port", str(self.port), "--parallel", str(self.parallel)],
                cwd=self.root,
                env=dict(os.environ),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        try:
            # The first start reads ~22 GB of weights; later starts hit the page cache.
            end = time.monotonic() + 600
            while time.monotonic() < end:
                check()
                if not self.running:
                    raise RuntimeError("Strata exited during startup; check data/strata/server.log")
                try:
                    if self._request("/health", timeout=2).get("loaded"):
                        log.info("Strata ready: %s, %d slots", self.model, self.parallel)
                        return
                except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
                    pass
                time.sleep(1)
            raise RuntimeError("Strata startup timed out")
        except Exception:
            self.stop()
            raise

    def chat(self, body):
        """One OpenAI chat completion; safe to call from several threads at once."""
        return self._request("/v1/chat/completions", body)

    def request_stop(self):
        """Nonblocking cancellation from the HTTP thread; only signal our own child."""
        if self.running:
            process = self.process
            try:
                process.terminate()
            except ProcessLookupError:
                return

            # SIGTERM takes Strata's clean QUIT path; escalate if the engine hangs.
            def kill_if_needed():
                if process.poll() is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass

            timer = threading.Timer(20, kill_if_needed)
            timer.daemon = True
            timer.start()

    def stop(self):
        process = self.process
        self.request_stop()
        if process is not None:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    raise MemoryPressure("The owned Strata process could not stop; GPU recovery is required") from None
        self.process = None
