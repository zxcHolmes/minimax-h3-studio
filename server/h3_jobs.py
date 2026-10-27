"""SQLite-backed job records. Safe to call from the HTTP loop and the worker thread."""

import json
import sqlite3
import threading
import time
import uuid

COLUMNS = (
    "id", "status", "mode", "preset", "prompt", "width", "height", "duration", "seed",
    "image", "video", "thumb", "stage", "progress", "error", "result",
    "created_at", "started_at", "finished_at", "last_image", "refs", "lora", "lora_strength",
    "picture", "audio", "lyrics", "guide_audio", "audio_start", "sampler", "steps", "source", "upscaler",
    "ref_videos", "model_3d", "mesh_options", "image_model",
)
JSON_COLUMNS = ("result", "refs", "ref_videos", "mesh_options")

ACTIVE = ("queued", "running")


class JobStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "id TEXT PRIMARY KEY, status TEXT, mode TEXT, preset TEXT, prompt TEXT, "
                "width INTEGER, height INTEGER, duration REAL, seed INTEGER, image TEXT, "
                "video TEXT, thumb TEXT, stage TEXT, progress REAL, error TEXT, result TEXT, "
                "created_at REAL, started_at REAL, finished_at REAL, last_image TEXT, refs TEXT, lora TEXT, "
                "lora_strength REAL, picture TEXT, audio TEXT, lyrics TEXT, guide_audio TEXT, "
                "audio_start REAL, sampler TEXT, steps INTEGER, source TEXT, upscaler TEXT, ref_videos TEXT)")
            # Databases created before the last-frame, reference, LoRA, picture, music, audio-guide, sampler, steps, upscale and
            # reference video options lack these.
            existing = {r["name"] for r in self._db.execute("PRAGMA table_info(jobs)")}
            for column, kind in (("last_image", "TEXT"), ("refs", "TEXT"), ("lora", "TEXT"),
                                 ("lora_strength", "REAL"), ("picture", "TEXT"),
                                 ("audio", "TEXT"), ("lyrics", "TEXT"), ("guide_audio", "TEXT"),
                                 ("audio_start", "REAL"), ("sampler", "TEXT"), ("steps", "INTEGER"),
                                 ("source", "TEXT"), ("upscaler", "TEXT"), ("ref_videos", "TEXT"),
                                 ("model_3d", "TEXT"), ("mesh_options", "TEXT"), ("image_model", "TEXT")):
                if column not in existing:
                    self._db.execute(f"ALTER TABLE jobs ADD COLUMN {column} {kind}")
            self._db.commit()

    def create(self, **fields):
        job = {c: None for c in COLUMNS}
        job.update(self._encode(fields), id=uuid.uuid4().hex[:12], status="queued", progress=0.0,
                   created_at=time.time())
        with self._lock:
            self._db.execute(f"INSERT INTO jobs ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
                             [job[c] for c in COLUMNS])
            self._db.commit()
        return self.get(job["id"])

    def update(self, job_id, **fields):
        fields = self._encode(fields)
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", [*fields.values(), job_id])
            self._db.commit()

    def get(self, job_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone()
        return self._decode(row) if row else None

    @staticmethod
    def _mode_filter(modes, image_model=None):
        clauses, params = [], []
        if modes is not None:
            clauses.append("mode IN (" + ",".join("?" for _ in modes) + ")")
            params.extend(modes)
        if image_model is not None:
            clauses.append("COALESCE(image_model, 'moss') = ?")
            params.append(image_model)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params

    def list(self, limit=100, offset=0, modes=None, image_model=None):
        where, params = self._mode_filter(modes, image_model)
        with self._lock:
            rows = self._db.execute("SELECT * FROM jobs" + where +
                                    " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                                    [*params, limit, offset]).fetchall()
        return [self._decode(r) for r in rows]

    def count(self, modes=None, image_model=None):
        where, params = self._mode_filter(modes, image_model)
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM jobs" + where, params).fetchone()[0]

    def queued_ids(self):
        with self._lock:
            rows = self._db.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at").fetchall()
        return [r["id"] for r in rows]

    def delete(self, job_id):
        with self._lock:
            self._db.execute("DELETE FROM jobs WHERE id = ?", [job_id])
            self._db.commit()

    def backfill_lora(self, legacy):
        """Split old combined preset ids into resolution + LoRA; legacy maps preset -> (resolution, lora)."""
        with self._lock:
            for preset, (resolution, lora) in legacy.items():
                self._db.execute("UPDATE jobs SET preset = ?, lora = ? WHERE preset = ? AND lora IS NULL",
                                 [resolution, lora, preset])
            self._db.commit()

    def fail_running(self, reason):
        """A process restart loses the running job; queued jobs are re-queued by the caller."""
        with self._lock:
            self._db.execute("UPDATE jobs SET status = 'failed', error = ?, finished_at = ? "
                             "WHERE status = 'running'", [reason, time.time()])
            self._db.commit()

    @staticmethod
    def _encode(fields):
        return {k: json.dumps(v) if k in JSON_COLUMNS and not isinstance(v, (str, type(None))) else v
                for k, v in fields.items()}

    @staticmethod
    def _decode(row):
        job = dict(row)
        for column in JSON_COLUMNS:
            if job.get(column):
                job[column] = json.loads(job[column])
        job["refs"] = job["refs"] or []
        job["ref_videos"] = job["ref_videos"] or []
        return job
