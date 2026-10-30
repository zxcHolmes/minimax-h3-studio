"""Selected audio.cpp CUDA models and immutable download checksums. Standard library only."""

RUNTIME_VERSION = "v0.9.3"
RUNTIME_NAME = "audio-v0.9.3-bin-ubuntu-x64-cuda12.8-colab.tar.gz"
RUNTIME_URL = (
    "https://github.com/0xShug0/audio.cpp/releases/download/v0.9.3/" + RUNTIME_NAME
)
RUNTIME_SHA256 = "5be3e8d515fb244387de87958668ebb729d9442de6a53df12e4c718ea918419d"

# From the v0.9.3 model_specs packages; embedded GGUF includes tokenizers/codecs.
AUDIO_WEIGHTS = {
    "qwen3_tts_1_7b_base_q8_0": {
        "id": "qwen3_tts_1_7b_base_q8_0",
        "family": "qwen3_tts",
        "repo": "audio-cpp/audio.cpp-gguf",
        "path": "Qwen3-TTS-12Hz-1.7B-Base-GGUF/qwen3-tts-12hz-1.7b-base-q8_0_v2.gguf",
        "target": "Qwen3-TTS-12Hz-1.7B-Base-GGUF/qwen3-tts-12hz-1.7b-base-q8_0_v2.gguf",
        "size": 2695186240,
        "sha256": "92641a8022d521efd79a5db45e952589b3f2b781680f9abfcf26f075d37b86c6",
    },
    "qwen3_tts_1_7b_customvoice_q8_0": {
        "id": "qwen3_tts_1_7b_customvoice_q8_0",
        "family": "qwen3_tts",
        "repo": "audio-cpp/audio.cpp-gguf",
        "path": "Qwen3-TTS-12Hz-1.7B-CustomVoice-GGUF/qwen3-tts-12hz-1.7b-customvoice-q8_0.gguf",
        "target": "Qwen3-TTS-12Hz-1.7B-CustomVoice-GGUF/qwen3-tts-12hz-1.7b-customvoice-q8_0.gguf",
        "size": 2817055200,
        "sha256": "c8ac3f94b6e73f137c0e7ecc9270bc8faec7a476ff799b87e48844d1d0987ac3",
    },
    "qwen3_tts_1_7b_voicedesign_q8_0": {
        "id": "qwen3_tts_1_7b_voicedesign_q8_0",
        "family": "qwen3_tts",
        "repo": "audio-cpp/audio.cpp-gguf",
        "path": "Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf",
        "target": "Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf",
        "size": 2817000064,
        "sha256": "b86e03d1d2077bbaed157ab7a7fc646c3e309e69afa52c5e1c86b622b4715057",
    },
    "voxcpm2_q8_0": {
        "id": "voxcpm2_q8_0",
        "family": "voxcpm2",
        "repo": "audio-cpp/audio.cpp-gguf",
        "path": "VoxCPM2-GGUF/voxcpm2-q8_0.gguf",
        "target": "VoxCPM2-GGUF/voxcpm2-q8_0.gguf",
        "size": 2955007488,
        "sha256": "8df1faf274e1bdeedef1fd9ddd6aba6632536f66f2e080991d2352af35ceef72",
    },
    "omnivoice_q8_0": {
        "id": "omnivoice_q8_0",
        "family": "omnivoice",
        "repo": "audio-cpp/audio.cpp-gguf",
        "path": "OmniVoice-GGUF/omnivoice-q8_0.gguf",
        "target": "OmniVoice-GGUF/omnivoice-q8_0.gguf",
        "size": 1350296096,
        "sha256": "0e5a721edd1b08d9067ef66f40ded609a6b14f5a8445c703f9869736cabd350a",
    },
    "qwen3_asr_1_7b_q8_0": {
        "id": "qwen3_asr_1_7b_q8_0",
        "family": "qwen3_asr",
        "repo": "audio-cpp/audio.cpp-gguf",
        "path": "Qwen3-ASR-1.7B-GGUF/qwen3-asr-1.7b-q8_0.gguf",
        "target": "Qwen3-ASR-1.7B-GGUF/qwen3-asr-1.7b-q8_0.gguf",
        "size": 2473017600,
        "sha256": "3bc2462eca3a3a8f56abcd860d0943ffdc0546547dde55a9d08589607d6f3936",
    },
    "qwen3_forced_aligner_0_6b_q8_0": {
        "id": "qwen3_forced_aligner_0_6b_q8_0",
        "family": "qwen3_forced_aligner",
        "repo": "audio-cpp/audio.cpp-gguf",
        "path": "Qwen3-ForcedAligner-0.6B-GGUF/qwen3-forced-aligner-0.6b-q8_0.gguf",
        "target": "Qwen3-ForcedAligner-0.6B-GGUF/qwen3-forced-aligner-0.6b-q8_0.gguf",
        "size": 1129969856,
        "sha256": "bf4fec616f77a20d89a649cd1c97bda269644eeb3cf906d1f7488a52d71f7cb2",
    },
}

QWEN_VOICES = [
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
]
LANGUAGES = {
    "auto": "Auto",
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "pt": "Portuguese",
    "es": "Spanish",
    "it": "Italian",
}
OMNI_INSTRUCTION_GROUPS = [
    {"id": "gender", "label": "Gender", "values": ["male", "female"]},
    {
        "id": "age",
        "label": "Age",
        "values": ["child", "teenager", "young adult", "middle-aged", "elderly"],
    },
    {
        "id": "pitch",
        "label": "Pitch",
        "values": [
            "very low pitch",
            "low pitch",
            "moderate pitch",
            "high pitch",
            "very high pitch",
        ],
    },
    {"id": "delivery", "label": "Delivery", "values": ["whisper"]},
    {
        "id": "accent",
        "label": "Accent",
        "values": [
            "american accent",
            "british accent",
            "australian accent",
            "chinese accent",
            "canadian accent",
            "indian accent",
            "korean accent",
            "portuguese accent",
            "russian accent",
            "japanese accent",
        ],
    },
    {
        "id": "dialect",
        "label": "Chinese dialect",
        "values": [
            "河南话",
            "陕西话",
            "四川话",
            "贵州话",
            "云南话",
            "桂林话",
            "济南话",
            "石家庄话",
            "甘肃话",
            "宁夏话",
            "青岛话",
            "东北话",
        ],
    },
]
OMNI_ALIASES = dict(
    zip(
        [
            "男",
            "女",
            "儿童",
            "少年",
            "青年",
            "中年",
            "老年",
            "极低音调",
            "低音调",
            "中音调",
            "高音调",
            "极高音调",
            "耳语",
        ],
        [
            "male",
            "female",
            "child",
            "teenager",
            "young adult",
            "middle-aged",
            "elderly",
            "very low pitch",
            "low pitch",
            "moderate pitch",
            "high pitch",
            "very high pitch",
            "whisper",
        ],
    )
)


def omni_instruction(value):
    import re

    items = [
        OMNI_ALIASES.get(x.strip().lower(), x.strip().lower())
        for x in re.split("[,，]", value)
        if x.strip()
    ]
    valid = {v for group in OMNI_INSTRUCTION_GROUPS for v in group["values"]}
    if any(item not in valid for item in items):
        raise ValueError(
            "OmniVoice voice design uses its listed attributes, e.g. female, young adult, moderate pitch"
        )
    for group in OMNI_INSTRUCTION_GROUPS:
        if len(set(items).intersection(group["values"])) > 1:
            raise ValueError("Choose one OmniVoice attribute per category")
    return ", ".join(dict.fromkeys(items))


SPEECH_MODELS = {
    "qwen3_tts": {
        "label": "Qwen3-TTS 1.7B",
        "modes": ["generate", "clone", "design"],
        "voices": QWEN_VOICES,
        "language": True,
    },
    "voxcpm2": {
        "label": "VoxCPM2",
        "modes": ["generate", "clone", "design"],
        "voices": [],
        "language": False,
    },
    "omnivoice": {
        "label": "OmniVoice",
        "modes": ["generate", "clone", "design"],
        "voices": [],
        "language": True,
    },
}
ASR_MODELS = {
    "qwen3_asr": {
        "label": "Qwen3-ASR 1.7B",
        "timestamps": ["none", "word", "segment"],
        "timing_source": "forced_alignment",
    }
}
NATIVE_MODELS = {
    "qwen3_tts_generate": ("qwen3_tts", "qwen3_tts_1_7b_customvoice_q8_0", "tts"),
    "qwen3_tts_clone": ("qwen3_tts", "qwen3_tts_1_7b_base_q8_0", "tts"),
    "qwen3_tts_design": ("qwen3_tts", "qwen3_tts_1_7b_voicedesign_q8_0", "tts"),
    "voxcpm2": ("voxcpm2", "voxcpm2_q8_0", "tts"),
    "omnivoice": ("omnivoice", "omnivoice_q8_0", "tts"),
    "qwen3_asr": ("qwen3_asr", "qwen3_asr_1_7b_q8_0", "asr"),
}
AUDIO_GROUPS = ("audio", "audio-runtime", *SPEECH_MODELS, *ASR_MODELS)
AUDIO_CHECKSUMS = {
    f["target"].rsplit("/", 1)[-1]: f["sha256"] for f in AUDIO_WEIGHTS.values()
}
AUDIO_CHECKSUMS[RUNTIME_NAME] = RUNTIME_SHA256
AUDIO_CHECKSUMS["silero_vad_16k.safetensors"] = (
    "c59271c284ae9c8335d795d60e0bfdb71aaaceec578d9bd9ffc1b8153c319ea1"
)


def audio_manifest():
    items = [("audio-runtime", RUNTIME_URL, "", "packages", RUNTIME_NAME, "audio")]
    for f in AUDIO_WEIGHTS.values():
        folder, name = f["target"].rsplit("/", 1)
        group = "qwen3_asr" if f["family"] == "qwen3_forced_aligner" else f["family"]
        items.append((group, f["repo"], f["path"], folder, name, "audio"))
    items.append(
        (
            "qwen3_asr",
            "https://raw.githubusercontent.com/0xShug0/audio.cpp/v0.9.3/assets/framework/models/silero_vad/silero_vad_16k.safetensors",
            "",
            "Silero-VAD",
            "silero_vad_16k.safetensors",
            "audio",
        )
    )
    return items


def native_id(model, speech_mode="generate"):
    return f"qwen3_tts_{speech_mode}" if model == "qwen3_tts" else model


def model_info(model, speech_mode="generate"):
    key = native_id(model, speech_mode)
    if key not in NATIVE_MODELS:
        # Old job records remain readable after a model is retired.
        return {
            "id": model,
            "label": model.replace("_", " "),
            "runtime": "audio.cpp " + RUNTIME_VERSION,
            "backend": "cuda",
            "unet": model,
            "retired": True,
        }
    family, weight, task = NATIVE_MODELS[key]
    return {
        "id": model,
        "label": (SPEECH_MODELS | ASR_MODELS)[model]["label"],
        "runtime": "audio.cpp " + RUNTIME_VERSION,
        "backend": "cuda",
        "unet": AUDIO_WEIGHTS[weight]["target"].rsplit("/", 1)[-1],
        "task": task,
    }


def server_config(root, port, threads):
    models = []
    for id, (family, weight, task) in NATIVE_MODELS.items():
        entry = {
            "id": id,
            "family": family,
            "path": str(root / "models" / AUDIO_WEIGHTS[weight]["target"]),
            "task": task,
            "mode": "offline",
        }
        if family == "qwen3_asr":
            entry["session_options"] = {
                "qwen3_asr.vad_model_path": str(root / "models" / "Silero-VAD"),
                "qwen3_asr.forced_aligner_path": str(
                    root
                    / "models"
                    / AUDIO_WEIGHTS["qwen3_forced_aligner_0_6b_q8_0"]["target"]
                ),
            }
        models.append(entry)
    return {
        "host": "127.0.0.1",
        "port": port,
        "backend": "cuda",
        "device": 0,
        "threads": threads,
        "lazy_load": True,
        "max_loaded_models": 2,  # e.g. Qwen3-TTS CustomVoice + Base for mixed preset/clone casts
        "idle_unload_ms": 0,
        "min_free_memory_mb": 1024,
        "log_request_body": False,
        "models": models,
    }
