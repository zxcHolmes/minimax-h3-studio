"""Native ComfyUI Pixal3D: image → structure → shape cascade → PBR GLB.

Based on Comfy-Org/workflow_templates/3d_pixal3d_trellis2_image_to_model.json.
Uses the resident engine's worker, cancellation, DynamicVRAM and per-node cleanup.
"""

import time

from engine_errors import Canceled
from model_catalog import PIXAL_FILES, pixal_model_info
from run_h3 import load_image


def generate_3d(
    engine,
    *,
    image_path,
    model_path,
    thumb_path,
    seed,
    resolution,
    texture_size,
    remove_background,
    on_progress,
):
    import torch
    from comfy_extras import nodes_trellis2 as t
    from comfy_extras.nodes_bg_removal import (
        LoadBackgroundRemovalModel,
        RemoveBackground,
    )
    from comfy_extras.nodes_images import ImageCropToMask
    from comfy_extras.nodes_moge import LoadMoGeModel, MoGeInference, MoGeGeometryToFOV
    from comfy_extras.nodes_custom_sampler import CFGOverride
    from comfy_extras.nodes_model_advanced import ModelSamplingSD3, RescaleCFG
    from comfy_extras.nodes_mesh_postprocess import (
        RemeshMesh,
        DecimateMesh,
        MeshSmoothNormals,
        UnwrapMesh,
        BakeTextureFromVoxel,
        ApplyTextureToMesh,
    )
    from comfy_extras.nodes_save_3d import mesh_item_to_glb_bytes

    engine._cancel = False
    engine.mm.interrupt_current_processing(False)
    timings = {}
    current = "loading"

    def stage(name):
        nonlocal current
        engine._check()
        current = name
        timings[name] = time.perf_counter()
        on_progress(name, 0.0)

    def call(fn, **kwargs):
        engine._check()
        # Native V3 mesh nodes read cls.hidden even without a UI. Use the same
        # isolated class context as ComfyUI's executor, with empty hidden inputs.
        node = getattr(fn, "__self__", None)
        if isinstance(node, type) and hasattr(node, "PREPARE_CLASS_CLONE"):
            fn = getattr(node.PREPARE_CLASS_CLONE(None), fn.__name__)
        result = fn(**kwargs)
        engine._after_node()
        engine._check()
        return result

    def sample(model, positive, negative, latent, steps, cfg, scheduler="normal"):
        return call(
            engine.nodes.KSampler().sample,
            model=model,
            seed=seed,
            steps=steps,
            cfg=cfg,
            sampler_name="euler",
            scheduler=scheduler,
            positive=positive,
            negative=negative,
            latent_image=latent,
            denoise=1.0,
        )[0]

    def hook(value, total, preview, node_id=None):
        engine._check()
        if total:
            on_progress(current, value / total)

    engine.utils.set_progress_bar_global_hook(hook)
    try:
        with torch.inference_mode():
            stage("loading")
            if engine._pixal is None:
                model = call(
                    engine.nodes.UNETLoader().load_unet,
                    unet_name=PIXAL_FILES[0][2],
                    weight_dtype="default",
                )[0]
                vision = call(
                    engine.nodes.CLIPVisionLoader().load_clip,
                    clip_name=PIXAL_FILES[1][2],
                )[0]
                shape_vae = call(
                    engine.nodes.VAELoader().load_vae, vae_name=PIXAL_FILES[2][2]
                )[0]
                tex_vae = call(
                    engine.nodes.VAELoader().load_vae, vae_name=PIXAL_FILES[3][2]
                )[0]
                moge = call(LoadMoGeModel.execute, model_name=PIXAL_FILES[4][2])[0]
                engine._pixal = (model, vision, shape_vae, tex_vae, moge, None)
            model, vision, shape_vae, tex_vae, moge, bg = engine._pixal
            stage("preprocessing")
            image = load_image(image_path)
            if remove_background:
                if bg is None:
                    bg = call(
                        LoadBackgroundRemovalModel.execute,
                        bg_removal_name=PIXAL_FILES[5][2],
                    )[0]
                    engine._pixal = (model, vision, shape_vae, tex_vae, moge, bg)
                mask = call(RemoveBackground.execute, bg_removal_model=bg, image=image)[
                    0
                ]
            else:
                from PIL import Image
                import numpy as np

                with Image.open(image_path) as original:
                    rgba = original.convert("RGBA")
                    mask = (
                        torch.from_numpy(np.array(rgba.getchannel("A")).copy())
                        .float()
                        .unsqueeze(0)
                        / 255
                    )
            image = call(
                ImageCropToMask.execute,
                images=image,
                masks=mask,
                width=1024,
                height=1024,
                pad_factor=1.1,
                grow_mask=0,
                background="#000000",
            )[0]
            engine._save_thumb(image[0], thumb_path)
            geometry = call(
                MoGeInference.execute,
                moge_model=moge,
                image=image,
                resolution_level=9,
                fov_x_degrees=0,
                batch_size=1,
                force_projection=True,
                apply_mask=True,
                refine_steps=3,
            )[0]
            fov = call(
                MoGeGeometryToFOV.execute,
                moge_geometry=geometry,
                axis="horizontal",
                unit="degrees",
            )[0]
            positive, negative = call(
                t.Pixal3DConditioning.execute,
                clip_vision_model=vision,
                image=image,
                camera_angle_x=fov,
            )
            # Match the official CFG cutoffs/rescale and sigma shift for each stage.
            structure_model = call(
                CFGOverride.execute,
                model=model,
                cfg=1,
                start_percent=0.667,
                end_percent=1,
            )[0]
            structure_model = RescaleCFG().patch(model=structure_model, multiplier=0.7)[
                0
            ]
            structure_model = ModelSamplingSD3().patch(model=structure_model, shift=5)[
                0
            ]
            shape_model = call(
                CFGOverride.execute,
                model=model,
                cfg=1,
                start_percent=0.769,
                end_percent=1,
            )[0]
            shape_model = RescaleCFG().patch(model=shape_model, multiplier=0.5)[0]
            texture_model = model

            stage("structure")
            latent = call(t.EmptyTrellis2LatentStructure.execute, batch_size=1)[0]
            latent = sample(structure_model, positive, negative, latent, 12, 7.5)
            voxel = call(
                t.VaeDecodeStructureTrellis2.execute,
                samples=latent,
                vae=shape_vae,
                resolution="32",
            )[0]
            stage("shape")
            pos, neg, latent = call(
                t.Trellis2ShapeStage.execute,
                positive=positive,
                negative=negative,
                voxel=voxel,
            )
            latent = sample(shape_model, pos, neg, latent, 20, 7.5)
            stage("shape_detail")
            pos, neg, latent = call(
                t.Trellis2UpsampleStage.execute,
                positive=pos,
                negative=neg,
                shape_latent=latent,
                vae=shape_vae,
                target_resolution=resolution,
            )
            latent = sample(shape_model, pos, neg, latent, 12, 7.5, "simple")
            mesh, subdivides = call(
                t.VaeDecodeShapeTrellis.execute, samples=latent, vae=shape_vae
            )
            stage("texture")
            pos, neg, tex_latent = call(
                t.Trellis2TextureStage.execute,
                positive=pos,
                negative=neg,
                shape_latent=latent,
            )
            tex_latent = sample(texture_model, pos, neg, tex_latent, 12, 1)
            colors = call(
                t.VaeDecodeTextureTrellis.execute,
                samples=tex_latent,
                vae=tex_vae,
                shape_subdivides=subdivides,
            )[0]
            stage("meshing")
            # 100k triangles and a 2K texture make the asset usable in a browser.
            engine.mm.unload_all_models()
            engine.mm.soft_empty_cache()
            reference_mesh = mesh
            # The decoded surface contains cracks and overlapping shells. Match
            # the official solid reconstruction before simplification/UV baking.
            mesh = call(
                RemeshMesh.execute,
                mesh=mesh,
                resolution=768,
                sign_mode={"sign_mode": "solid", "fill": 20.0, "qef": False},
                band=1.0,
                project_back=0.0,
                fix_poles=False,
                smooth_iters=20,
                drop_small_components=0.01,
                precluster_max_verts=20000000,
            )[0]
            mesh = call(
                DecimateMesh.execute,
                mesh=mesh,
                target_face_count=100000,
                placement_mode={"placement_mode": "midpoint"},
            )[0]
            mesh = call(
                UnwrapMesh.execute,
                mesh=mesh,
                segmenter="pec",
                resolution=texture_size,
                padding=1,
                weld_distance=0.0002,
            )[0]
            mesh = call(MeshSmoothNormals.execute, mesh=mesh, crease_angle=180)[0]
            base, metallic, roughness = call(
                BakeTextureFromVoxel.execute,
                mesh=mesh,
                voxel_colors=colors,
                texture_size=texture_size,
                reference_mesh=reference_mesh,
            )
            mesh = call(
                ApplyTextureToMesh.execute,
                mesh=mesh,
                base_color=base,
                metallic=metallic,
                roughness=roughness,
            )[0]
            stage("saving")
            data = mesh_item_to_glb_bytes(mesh, 0)
            if not data:
                raise ValueError("Pixal3D produced an empty mesh")
            # Publish only complete assets.
            part = model_path.with_suffix(".glb.part")
            part.write_bytes(data)
            part.replace(model_path)
            result = {
                "vertices": int(mesh.vertices.shape[-2]),
                "faces": int(mesh.faces.shape[-2]),
                "bytes": len(data),
                "resolution": resolution,
                "texture_size": texture_size,
                "remove_background": remove_background,
                "remesh": {"mode": "solid", "resolution": 768},
                "models": pixal_model_info(),
            }
    except engine.mm.InterruptProcessingException:
        raise Canceled()
    finally:
        engine.utils.set_progress_bar_global_hook(None)
        engine.mm.interrupt_current_processing(False)
        engine._after_node()
    end = time.perf_counter()
    names = list(timings)
    result["timings"] = {
        n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
        for i, n in enumerate(names)
    }
    return result
