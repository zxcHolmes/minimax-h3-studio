"""Image model choices, capabilities, exact workflow defaults and download manifest."""

import math

# Picture generation: MOSS-Image SFT with the settings of ComfyUI's MOSS-Image text-to-image template.
MOSS_REPO = "Comfy-Org/MOSS-Image"
MOSS_UNET = "moss_image_sft_int8_convrot.safetensors"
MOSS_CLIP = "qwen3.5_9b_w4a8_gptq.safetensors"
MOSS_VAE = "flux2-vae_small.safetensors"
IMAGE = {
    "steps": 25,
    "cfg": 2.5,
    "sampler": "er_sde",
    "scheduler": "simple",
    "negative": "nsfw, worst quality, bad anatomy, watermark, jpeg artifact",
}
IMAGE_AREA = 1024 * 1024

# Only the distilled 4-step Klein checkpoint and the standalone 8-step Qwen Turbo.
KLEIN_REPO = "Comfy-Org/Flux-2-Klein-4B"
QWEN_REPO = "Comfy-Org/Qwen-Image-2.1"
IMAGE_MODELS = {
    "moss": {
        "label": "MOSS-Image",
        "unet": MOSS_UNET,
        "clip": MOSS_CLIP,
        "vae": MOSS_VAE,
        "clip_type": "moss_image",
        "steps": 25,
        "cfg": 2.5,
        "sampler": "er_sde",
        "scheduler": "simple",
        "max_refs": 0,
    },
    "flux-klein-4b": {
        "label": "FLUX.2 Klein 4B",
        "unet": "flux-2-klein-4b.safetensors",
        "clip": "qwen_3_4b.safetensors",
        "vae": "flux2-vae-klein.safetensors",
        "clip_type": "flux2",
        "steps": 4,
        "cfg": 1.0,
        "sampler": "euler",
        "scheduler": "flux2",
        "max_refs": 4,
    },
    "qwen-image-21-turbo": {
        "label": "Qwen Image 2.1 Turbo",
        "unet": "qwen_image_2.1_turbo_int8_convrot.safetensors",
        "clip": "qwen3vl_8b_int8_convrot.safetensors",
        "vae": "qwen_image_2.1_vae_bf16.safetensors",
        "clip_type": "qwen_image",
        "steps": 8,
        "cfg": 1.0,
        "sampler": "euler",
        "scheduler": "manual",
        "max_refs": 4,
    },
}
QWEN_TURBO_SIGMAS = (
    1.0,
    0.978453,
    0.95418,
    0.926626,
    0.89508,
    0.845148,
    0.704534,
    0.414568,
    0.0,
)

# group, repo, repository path, local models folder, filename
IMAGE_FILES = [
    (
        "klein",
        KLEIN_REPO,
        "split_files/diffusion_models/flux-2-klein-4b.safetensors",
        "diffusion_models",
        "flux-2-klein-4b.safetensors",
    ),
    (
        "klein",
        KLEIN_REPO,
        "split_files/text_encoders/qwen_3_4b.safetensors",
        "text_encoders",
        "qwen_3_4b.safetensors",
    ),
    (
        "klein",
        KLEIN_REPO,
        "split_files/vae/flux2-vae.safetensors",
        "vae",
        "flux2-vae-klein.safetensors",
    ),
    (
        "qwen-image",
        QWEN_REPO,
        "diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors",
        "diffusion_models",
        "qwen_image_2.1_turbo_int8_convrot.safetensors",
    ),
    (
        "qwen-image",
        QWEN_REPO,
        "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
        "text_encoders",
        "qwen3vl_8b_int8_convrot.safetensors",
    ),
    (
        "qwen-image",
        QWEN_REPO,
        "vae/qwen_image_2.1_vae_bf16.safetensors",
        "vae",
        "qwen_image_2.1_vae_bf16.safetensors",
    ),
]
# Official Hugging Face LFS SHA256s: verify new downloads before publishing them.
IMAGE_CHECKSUMS = {
    "flux-2-klein-4b.safetensors": "ec3d4e733a771f61c052fb4856c48b336c55eaf2c65487c2a1faeb9bbda7a343",
    "qwen_3_4b.safetensors": "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
    "flux2-vae-klein.safetensors": "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3",
    "qwen_image_2.1_turbo_int8_convrot.safetensors": "8144a0182964aa8403ad6dbc011db837304167d235161b9aabaa8532e967314c",
    "qwen3vl_8b_int8_convrot.safetensors": "8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f",
    "qwen_image_2.1_vae_bf16.safetensors": "bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9",
}


def image_model_info(model="moss"):
    p = IMAGE_MODELS[model]
    return {
        "id": model,
        "unet": p["unet"],
        "text_encoder": p["clip"],
        "vae": p["vae"],
        "lora": None,
        "lora_strength": None,
        "steps": p["steps"],
        "sampler": p["sampler"],
        "scheduler": p["scheduler"],
        "cfg": p["cfg"],
    }


def picture_size(model, ratio):
    multiple = 32 if model == "qwen-image-21-turbo" else 16
    return (
        max(multiple, round(math.sqrt(IMAGE_AREA * ratio) / multiple) * multiple),
        max(multiple, round(math.sqrt(IMAGE_AREA / ratio) / multiple) * multiple),
    )
