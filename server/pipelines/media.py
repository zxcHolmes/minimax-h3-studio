"""Media pipeline and helpers."""

import math
from model_catalog import FPS, frame_count


def _ref_video(path, width, height, frames):
    """(IMAGE, AUDIO or None) for a reference video: its first `frames` frames at 24 fps, scaled down (keeping
    the aspect) to the generation's pixel area, and the same stretch of its soundtrack. The node would put the
    video on a 1344×768 canvas whatever the job's size, and its tokens join every attention call, so a full
    size reference can triple a 544p job's sequence and run out of memory."""
    import av
    import numpy as np
    import torch
    from comfy_extras.nodes_audio import load

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        w, h = stream.codec_context.width, stream.codec_context.height
        scale = min(1.0, math.sqrt(width * height / (w * h)))
        tw, th = (
            max(32, round(w * scale / 32) * 32),
            max(32, round(h * scale / 32) * 32),
        )
        images = []
        for frame in container.decode(stream):
            # resample to 24 fps by timestamp: keep a frame once it reaches the next output slot
            if frame.time is not None and frame.time + 0.5 / FPS < len(images) / FPS:
                continue
            images.append(
                frame.reformat(width=tw, height=th, format="rgb24").to_ndarray()
            )
            if len(images) >= frames:
                break
        has_audio = bool(container.streams.audio)
    video = torch.from_numpy(np.stack(images)).float() / 255.0
    if not has_audio:
        return video, None
    waveform, rate = load(str(path))
    return video, {
        "waveform": waveform[:, : int(math.ceil(len(images) / FPS * rate))].unsqueeze(
            0
        ),
        "sample_rate": rate,
    }


def _audio_clip(path, start, duration):
    """The `duration`-long clip of an audio file from `start` seconds, as a ComfyUI AUDIO dict."""
    from comfy_extras.nodes_audio import load

    waveform, rate = load(str(path))
    begin = int(round(start * rate))
    end = begin + int(math.ceil(frame_count(duration) / FPS * rate))
    clip = waveform[:, begin:end]
    if clip.shape[1] < rate // 10:
        raise ValueError(f"the guide audio has nothing at {start:.2f} s")
    return {"waveform": clip.unsqueeze(0), "sample_rate": rate}


def _thumb_from_video(video_path, thumb_path):
    """Save the middle frame of a video as its thumbnail; returns the frame count."""
    import av
    import torch

    with av.open(str(video_path)) as container:
        total = container.streams.video[0].frames
        middle = None
        for i, frame in enumerate(container.decode(video=0)):
            if i == total // 2:
                middle = frame.to_ndarray(format="rgb24")
                break
    _save_thumb(torch.from_numpy(middle).float() / 255.0, thumb_path)
    return total


def _save_mp3(audio, path):
    """Encode the waveform as VBR mp3 V0 with PyAV, as ComfyUI's SaveAudioAdvanced does in the template."""
    import av

    wave = audio["waveform"][0].float().cpu()
    rate = audio["sample_rate"]
    layout = "mono" if wave.shape[0] == 1 else "stereo"
    with av.open(str(path), mode="w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=rate, layout=layout)
        stream.codec_context.qscale = 1
        frame = av.AudioFrame.from_ndarray(
            wave.movedim(0, 1).reshape(1, -1).numpy(), format="flt", layout=layout
        )
        frame.sample_rate = rate
        frame.pts = 0
        container.mux(stream.encode(frame))
        container.mux(stream.encode(None))


def _save_picture(frame, path):
    import numpy as np
    from PIL import Image

    pixels = (frame.clamp(0, 1).cpu().float().numpy() * 255).round().astype(np.uint8)
    Image.fromarray(pixels).save(path)


def _save_thumb(frame, path):
    import numpy as np
    from PIL import Image

    pixels = (frame.clamp(0, 1).cpu().float().numpy() * 255).round().astype(np.uint8)
    img = Image.fromarray(pixels)
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        img = background
    img.thumbnail((640, 640))
    img.save(path, quality=85)
