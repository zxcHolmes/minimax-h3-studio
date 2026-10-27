"""Resumable, checksum-verified downloads, with optional aria2 connections."""

import hashlib
import os
import shutil
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit


def download_token(url):
    target = urlsplit(url)
    endpoint = urlsplit(os.environ.get("HF_ENDPOINT") or "https://huggingface.co")
    if target.hostname in {endpoint.hostname, "huggingface.co", "hf-mirror.com"}:
        token = os.environ.get("HF_TOKEN")
        if token and target.scheme != "https":
            raise ValueError("HF_TOKEN requires an HTTPS download endpoint")
        return token
    return None


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and (
            urlsplit(req.full_url).netloc != urlsplit(newurl).netloc
            or urlsplit(newurl).scheme != "https"
        ):
            redirected.remove_header("Authorization")
        return redirected


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def verify_checksum(path, expected_sha256):
    if not expected_sha256:
        return
    digest = hashlib.sha256()
    with path.open("rb") as inp:
        while chunk := inp.read(8 << 20):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise IOError(f"SHA256 mismatch for {path.name}")
    print(f"    {path.name}: SHA256 verified", flush=True)


def download(url, dest, expected_sha256=None, connections=1):
    token = download_token(url)
    part = dest.with_name(dest.name + ".part")
    if connections > 1:
        aria2 = shutil.which("aria2c")
        if not aria2:
            raise RuntimeError(
                "--connections > 1 requires aria2c; use --connections 1 for urllib"
            )
        if token:
            raise RuntimeError(
                "use --connections 1 with HF_TOKEN to keep tokens out of process arguments"
            )
        subprocess.run(
            [
                aria2,
                "--continue=true",
                "--auto-file-renaming=false",
                "--allow-overwrite=true",
                "--file-allocation=none",
                f"--max-connection-per-server={connections}",
                f"--split={connections}",
                "--min-split-size=8M",
                "--console-log-level=warn",
                "--summary-interval=20",
                "--max-tries=5",
                "--retry-wait=3",
                f"--dir={dest.parent}",
                f"--out={part.name}",
                url,
            ],
            check=True,
        )
        verify_checksum(part, expected_sha256)
        part.rename(dest)
        return
    if part.with_name(part.name + ".aria2").exists():
        raise IOError(
            f"{part.name} has segmented resume data; rerun with --connections 8"
        )
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "minimax-h3-studio"}
    if have:
        headers["Range"] = f"bytes={have}-"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.build_opener(SafeRedirect()).open(
        urllib.request.Request(url, headers=headers), timeout=60
    ) as resp:
        if have and resp.status != 206:  # server ignored the range: start over
            have = 0
        total = have + int(resp.headers.get("Content-Length") or 0)
        mode = "ab" if have else "wb"
        done, last = have, 0.0
        with open(part, mode) as out:
            while chunk := resp.read(8 << 20):
                out.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last > 2 or done == total:
                    last = now
                    pct = f"{done / total:6.1%}" if total else ""
                    print(
                        f"\r    {dest.name}: {pct} {human(done)} / {human(total)}",
                        end="",
                        flush=True,
                    )
    print()
    if total and done != total:
        raise IOError(f"incomplete download: {done} of {total} bytes; rerun to resume")
    verify_checksum(part, expected_sha256)
    part.rename(dest)
