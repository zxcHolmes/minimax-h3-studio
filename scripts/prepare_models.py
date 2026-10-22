#!/usr/bin/env python3
"""Download every checkpoint the server uses into a ComfyUI models folder.

The file list comes from server/h3_engine.py (base DiTs, text encoder, VAEs and
every entry in LORAS), so adding a LoRA there is enough for it to be prepared.
Standard library only: run it with any Python 3.9+, no ComfyUI env needed.

    python scripts/prepare_models.py --comfyui /path/to/ComfyUI
    python scripts/prepare_models.py --list                 # show what would be fetched
    python scripts/prepare_models.py --skip ref2va larryvrh # leave out groups

Existing files are skipped; interrupted downloads resume from their .part file.
HF_ENDPOINT selects a mirror (e.g. https://hf-mirror.com), HF_TOKEN is sent if set.
ComfyUI itself and the larryvrh custom node are not installed by this script.
"""

import argparse
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from h3_engine import AUDIO_VAE, CLIP, LORAS, UNETS, VIDEO_VAE  # noqa: E402

COMFY_REPO = "Comfy-Org/MiniMax-H3"
LARRYVRH_NODE = "custom_nodes/ComfyUI-MiniMax-H3-Turbo"
GROUPS = ("shared", "fl2va", "ref2va", "lightx2v", "larryvrh")


def manifest():
    """(group, repo, path in repo, models subfolder, file name) for every checkpoint."""
    items = [
        ("shared", COMFY_REPO, f"text_encoders/{CLIP}", "text_encoders", CLIP),
        ("shared", COMFY_REPO, f"vae/{VIDEO_VAE}", "vae", VIDEO_VAE),
        ("shared", COMFY_REPO, f"vae/{AUDIO_VAE}", "vae", AUDIO_VAE),
    ]
    items += [(family, COMFY_REPO, f"diffusion_models/{name}", "diffusion_models", name)
              for family, name in UNETS.items()]
    for lora in LORAS.values():
        group = "larryvrh" if lora["loader"] == "larryvrh" else "lightx2v"
        items.append((group, lora["source"], lora["file"], "loras", lora["file"]))
    # A LoRA belongs to its family too, so skipping "ref2va" also skips the ref2v LoRAs.
    families = {lora["file"]: lora["family"] for lora in LORAS.values()}
    return [(g, repo, path, sub, name, families.get(name)) for g, repo, path, sub, name in items]


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def download(url, dest):
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "minimax-h3-studio"}
    if have:
        headers["Range"] = f"bytes={have}-"
    if os.environ.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
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
                    print(f"\r    {pct} {human(done)} / {human(total)}", end="", flush=True)
    print()
    part.rename(dest)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--comfyui", default=os.environ.get("H3_COMFYUI"),
                   help="ComfyUI checkout (default: $H3_COMFYUI)")
    p.add_argument("--skip", nargs="*", default=[], choices=GROUPS, metavar="GROUP",
                   help=f"groups to leave out: {', '.join(GROUPS)}")
    p.add_argument("--list", action="store_true", help="print the files and exit")
    args = p.parse_args()

    endpoint = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
    items = [it for it in manifest() if it[0] not in args.skip and it[5] not in args.skip]

    if args.list or not args.comfyui:
        for group, repo, path, sub, name, _ in items:
            print(f"{group:9} models/{sub}/{name}  <-  {repo}/{path}")
        if not args.comfyui and not args.list:
            p.error("--comfyui (or $H3_COMFYUI) is required to download")
        return

    models = Path(args.comfyui).expanduser() / "models"
    if not models.is_dir():
        p.error(f"{models} does not exist; point --comfyui at a ComfyUI checkout")

    failed = []
    for i, (group, repo, path, sub, name, _) in enumerate(items, 1):
        dest = models / sub / name
        if dest.exists():
            print(f"[{i}/{len(items)}] ok      {sub}/{name}")
            continue
        print(f"[{i}/{len(items)}] fetch   {sub}/{name}  ({repo})")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            download(f"{endpoint}/{repo}/resolve/main/{path}", dest)
        except Exception as e:  # keep going; the .part file lets a rerun resume
            print(f"\n    failed: {e}")
            failed.append(name)

    if "larryvrh" not in args.skip and not (Path(args.comfyui).expanduser() / LARRYVRH_NODE).is_dir():
        print(f"\nnote: the larryvrh LoRA also needs its ComfyUI node:\n"
              f"    git clone https://github.com/larryvrh/ComfyUI-MiniMax-H3-Turbo {args.comfyui}/{LARRYVRH_NODE}")
    if failed:
        print(f"\n{len(failed)} download(s) failed: {', '.join(failed)}; rerun to resume.")
        sys.exit(1)
    print("\nall models ready")


if __name__ == "__main__":
    main()
