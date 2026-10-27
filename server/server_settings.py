"""Environment-backed server configuration and data paths; no process-wide mutable state."""

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_SEED = 2**48
MAX_PROMPT = 20000
DURATION_RANGE = (2.0, 15.0)
HISTORY_KINDS = {
    "video": ("t2v", "i2v", "fl2v", "r2v", "upscale"),
    "image": ("t2i", "i2i"),
    "music": ("t2m",),
    "3d": ("i23d",),
}


@dataclass(frozen=True)
class ServerSettings:
    comfyui: Path | None
    data: Path
    web_dist: Path
    host: str = "0.0.0.0"
    port: int = 8190
    comfy_args: tuple = ("--enable-triton-backend", "--use-sage-attention")

    @classmethod
    def from_env(cls):
        return cls(
            comfyui=Path(os.environ["H3_COMFYUI"])
            if os.environ.get("H3_COMFYUI")
            else None,
            data=Path(os.environ.get("H3_DATA", ROOT / "data")).resolve(),
            web_dist=Path(os.environ.get("H3_WEB_DIST", ROOT / "web_dist")).resolve(),
            host=os.environ.get("H3_HOST", "0.0.0.0"),
            port=int(os.environ.get("H3_PORT", "8190")),
            comfy_args=tuple(
                shlex.split(
                    os.environ.get(
                        "H3_COMFY_ARGS", "--enable-triton-backend --use-sage-attention"
                    )
                )
            ),
        )

    @property
    def videos(self):
        return self.data / "videos"

    @property
    def pictures(self):
        return self.data / "pictures"

    @property
    def music(self):
        return self.data / "music"

    @property
    def thumbs(self):
        return self.data / "thumbs"

    @property
    def uploads(self):
        return self.data / "uploads"

    @property
    def models3d(self):
        return self.data / "models3d"

    def prepare_directories(self):
        for path in (
            self.data,
            self.videos,
            self.pictures,
            self.music,
            self.thumbs,
            self.uploads,
            self.models3d,
        ):
            path.mkdir(parents=True, exist_ok=True)
