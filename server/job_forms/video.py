"""Video-mode validation, references, sampling overrides and canvas selection."""

from model_catalog import (
    ASPECT_RATIOS,
    DEFAULT_LORAS,
    LORAS,
    LORA_STRENGTH_RANGE,
    MAX_REFS,
    MAX_REF_VIDEOS,
    SAMPLERS,
    STEPS_RANGE,
    canvas_size,
    fixed_sampling,
    with_keyframe_prefix,
)


from job_uploads import read_image, read_video, read_audio, save_upload


def video_fields(form, common, settings):
    prompt, resolution, duration, seed = (
        common[k] for k in ("prompt", "resolution", "duration", "seed")
    )
    try:
        first, last = (
            read_image("image", form.get("image")),
            read_image("last_image", form.get("last_image")),
        )
        refs = [read_image("ref_image", u) for u in form.getall("ref_image", [])]
    except ValueError as e:
        raise ValueError(str(e))
    refs = [r for r in refs if r]
    try:
        ref_videos = [
            v for v in (read_video(u) for u in form.getall("ref_video", [])) if v
        ]
        guide = read_audio(form.get("audio"))
        audio_start = float(form.get("audio_start") or 0)
    except ValueError as e:
        raise ValueError(str(e))
    if guide and not 0 <= audio_start < guide[2] - 0.5:
        raise ValueError(f"audio_start must be within the audio's {guide[2]:.1f} s")
    if last and not first:
        raise ValueError("a last frame needs a first frame")
    if len(refs) > MAX_REFS:
        raise ValueError(f"at most {MAX_REFS} reference images")
    if len(ref_videos) > MAX_REF_VIDEOS:
        raise ValueError(f"at most {MAX_REF_VIDEOS} reference videos")
    # Reference images or a ref2va model choice pick the ref2va DiT (which also runs with no references);
    # everything else runs on fl2va.
    lora = form.get("lora")
    if lora and lora not in LORAS:
        raise ValueError(f"unknown lora {lora}")
    family = (
        "ref2va"
        if refs or ref_videos or (lora and LORAS[lora]["family"] == "ref2va")
        else "fl2va"
    )
    if family == "ref2va" and (first or last):
        raise ValueError(
            "ref2va jobs take ref_image / ref_video, not image / last_image"
        )
    lora = lora or DEFAULT_LORAS[family][resolution]
    if LORAS[lora]["family"] != family:
        raise ValueError(f"lora {lora} is for {LORAS[lora]['family']} jobs")
    if resolution not in LORAS[lora]["resolutions"]:
        raise ValueError(
            f"lora {lora} supports {', '.join(LORAS[lora]['resolutions'])}"
        )
    try:
        lora_strength = round(float(form.get("lora_strength") or 1.0), 2)
    except ValueError:
        raise ValueError("lora_strength must be a number")
    if not LORA_STRENGTH_RANGE[0] <= lora_strength <= LORA_STRENGTH_RANGE[1]:
        raise ValueError(f"lora_strength must be within {LORA_STRENGTH_RANGE}")
    if not LORAS[lora]["file"]:
        lora_strength = 1.0  # FastH3 bases have no LoRA to scale
    sampler = form.get("sampler") or None
    if sampler and sampler not in SAMPLERS:
        raise ValueError(f"sampler must be one of {', '.join(SAMPLERS)}")
    if fixed_sampling(lora) or sampler == LORAS[lora].get("sampler", "euler"):
        sampler = None  # larryvrh and FastH3 keep their own sampler; the model choice's own needs no override
    try:
        steps = int(form.get("steps") or 0) or None
    except ValueError:
        raise ValueError("steps must be an integer")
    if steps and not STEPS_RANGE[0] <= steps <= STEPS_RANGE[1]:
        raise ValueError(f"steps must be within {STEPS_RANGE}")
    if steps == LORAS[lora]["steps"] or fixed_sampling(lora):
        steps = None

    image_name = save_upload(first, settings.uploads) if first else None
    last_name = save_upload(last, settings.uploads) if last else None
    ref_names = [save_upload(r, settings.uploads) for r in refs]
    ref_video_names = [save_upload(v, settings.uploads) for v in ref_videos]
    guide_name = save_upload(guide, settings.uploads) if guide else None

    aspect = form.get("aspect_ratio") or "16:9"
    if aspect == "image" and (first or refs or ref_videos):
        w, h = (first or (refs or ref_videos)[0])[2]
        ratio = w / h
    elif aspect in ASPECT_RATIOS:
        ratio = ASPECT_RATIOS[aspect]
    else:
        raise ValueError(f"unknown aspect ratio {aspect}")
    width, height = canvas_size(resolution, ratio)

    mode = (
        "r2v"
        if family == "ref2va"
        else "fl2v"
        if last_name
        else "i2v"
        if image_name
        else "t2v"
    )
    if image_name:
        prompt = with_keyframe_prefix(prompt, duration, last_frame=bool(last_name))
    return dict(
        mode=mode,
        preset=resolution,
        lora=lora,
        lora_strength=lora_strength,
        sampler=sampler,
        steps=steps,
        prompt=prompt,
        width=width,
        height=height,
        duration=duration,
        seed=seed,
        image=image_name,
        last_image=last_name,
        refs=ref_names,
        ref_videos=ref_video_names,
        guide_audio=guide_name,
        audio_start=audio_start if guide_name else None,
    )
