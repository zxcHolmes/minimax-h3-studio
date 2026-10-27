"""Preserve native ASR timings and export honest word/segment subtitles."""

import json
import math
import re


def spans(rows, rate, duration, text_key):
    out = []
    for row in rows or []:
        if "start_sample" not in row or "end_sample" not in row:
            continue
        start, end = row["start_sample"] / rate, row["end_sample"] / rate
        text = str(row.get(text_key, "")).strip()
        if (
            not text
            or not all(math.isfinite(n) for n in (start, end))
            or not 0 <= start < end
        ):
            continue
        start, end = min(start, duration), min(end, duration)
        if end <= start:
            continue
        value = {"start": round(start, 3), "end": round(end, 3), "text": text}
        if "speaker_id" in row:
            value["speaker"] = str(row["speaker_id"])
        out.append(value)
    return out


def group_words(words):
    """Cue bounds come only from aligned words, not invented per-character timings."""
    cues, group = [], []

    def flush():
        if group:
            chunks = [w["text"] for w in group]
            text = " ".join(chunks)
            text = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", text)
            cues.append(
                {"start": group[0]["start"], "end": group[-1]["end"], "text": text}
            )
            group.clear()

    for word in words:
        if group and (
            word["start"] - group[-1]["end"] > 0.7
            or word["end"] - group[0]["start"] > 6
            or sum(len(w["text"]) for w in group) + len(word["text"]) > 48
        ):
            flush()
        group.append(word)
        if re.search(r"[。！？.!?]$", word["text"]):
            flush()
    flush()
    return cues


def clock(seconds, separator):
    millis = round(seconds * 1000)
    return f"{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02}{separator}{millis % 1000:03}"


def export_transcript(raw, *, folder, job_id, duration, timing_source):
    text = str(raw.get("text", "")).strip()
    rate = raw.get("sample_rate")
    words = spans(raw.get("words"), rate, duration, "word") if rate and rate > 0 else []
    segments = (
        spans(raw.get("segments"), rate, duration, "text") if rate and rate > 0 else []
    )
    turns = (
        spans(raw.get("speaker_turns"), rate, duration, "text")
        if rate and rate > 0
        else []
    )
    if timing_source == "none":
        # Untimed requests must not acquire inferred timestamp spans.
        words, segments, turns = [], [], []
    cues = segments or turns or group_words(words)
    result = {
        "text": text,
        "language": raw.get("language"),
        "duration": duration,
        "words": words,
        "segments": cues,
        "speaker_turns": turns,
        "timing_source": timing_source if cues or words else "none",
        "segment_source": "native"
        if segments or turns
        else "grouped_aligned_words"
        if words
        else "none",
        "timing": raw.get("timing", {}),
    }
    exports = {}

    def write(key, suffix, content):
        name = job_id + suffix
        (folder / name).write_text(content, encoding="utf-8")
        exports[key] = name

    write("txt", ".txt", text + "\n")
    write(
        "json",
        ".json",
        json.dumps({**result, "native": raw}, ensure_ascii=False, indent=2),
    )
    if words:
        write("words", ".words.json", json.dumps(words, ensure_ascii=False, indent=2))
    if cues:
        srt, vtt = [], ["WEBVTT\n"]
        for i, cue in enumerate(cues, 1):
            line = (f"Speaker {cue['speaker']}: " if "speaker" in cue else "") + cue[
                "text"
            ]
            srt.append(
                f"{i}\n{clock(cue['start'], ',')} --> {clock(cue['end'], ',')}\n{line}\n"
            )
            vtt.append(
                f"{clock(cue['start'], '.')} --> {clock(cue['end'], '.')}\n{line}\n"
            )
        write("srt", ".srt", "\n".join(srt))
        write("vtt", ".vtt", "\n".join(vtt))
    return {**result, "exports": exports}
