"""IC-Light (SD 1.5, foreground-conditioned): redraws a picture's lighting to follow a hint.

Ported from the official demo, gradio_demo.py in github.com/lllyasviel/IC-Light
(Apache-2.0): the UNet takes four extra input channels holding the picture to
relight, IC-Light's weights are added on top of the base model's, and the
diffusion starts from the encoded lighting hint instead of from pure noise.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import safetensors.torch
import torch
from diffusers import (
    AutoencoderKL,
    DPMSolverMultistepScheduler,
    StableDiffusionImg2ImgPipeline,
    UNet2DConditionModel,
)
from PIL import Image
from transformers import CLIPTextModel, CLIPTokenizer

from relight_backend.utils.device import release_memory

QUALITY_PROMPT = "best quality"
NEGATIVE_PROMPT = "lowres, bad anatomy, bad hands, cropped, worst quality"
OFFSETS_FILE = "iclight_sd15_fc.safetensors"


@dataclass(frozen=True)
class RelightParams:
    prompt: str = "beautiful lighting, natural"
    steps: int = 25
    guidance: float = 2.0
    denoise: float = 0.75  # how far the result may move away from the hint, 0..1
    seed: int = 12345
    # Second pass at a larger size for detail; needs more memory and time.
    highres: bool = True
    highres_scale: float = 1.5
    highres_denoise: float = 0.5


def round64(value: float) -> int:
    return max(64, int(round(value / 64.0)) * 64)


def _to_tensor(image: Image.Image) -> torch.Tensor:
    """RGB image to (1, 3, H, W) in -1..1 (127 maps to exactly 0, as in the demo)."""
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 127.0 - 1.0
    return torch.from_numpy(array).movedim(-1, 0)[None]


def _to_image(pixels: torch.Tensor) -> Image.Image:
    array = (pixels[0].movedim(0, -1).float() * 127.5 + 127.5).clamp(0, 255)
    return Image.fromarray(array.cpu().numpy().astype(np.uint8), mode="RGB")


class IcLight:
    def __init__(self) -> None:
        self._pipe: Any = None
        self.device = torch.device("cpu")
        self.dtype = torch.float32

    def load(self, base: Path, offsets: Path, device: torch.device, dtype: torch.dtype,
             low_memory: bool = False) -> None:
        """`base`: the SD 1.5 model folder. `offsets`: folder holding IC-Light's weights."""
        self.device, self.dtype = device, dtype
        tokenizer = CLIPTokenizer.from_pretrained(base, subfolder="tokenizer")
        # Any: these libraries' own type hints are incomplete.
        text_encoder: Any = CLIPTextModel.from_pretrained(base, subfolder="text_encoder")
        vae: Any = AutoencoderKL.from_pretrained(base, subfolder="vae")
        unet: Any = UNet2DConditionModel.from_pretrained(base, subfolder="unet")

        # Eight input channels: the four noisy latent channels plus the picture's latent.
        with torch.no_grad():
            old = unet.conv_in
            wider = torch.nn.Conv2d(8, old.out_channels, old.kernel_size, old.stride, old.padding)
            wider.weight.zero_()
            wider.weight[:, :4].copy_(old.weight)
            wider.bias = old.bias
            unet.conv_in = wider

        original_forward = unet.forward

        def forward_with_picture(sample: torch.Tensor, timestep: Any,
                                 encoder_hidden_states: torch.Tensor, **kwargs: Any) -> Any:
            # The pipeline has no argument for the extra channels, so they ride in
            # cross_attention_kwargs and are taken out again here.
            picture = kwargs["cross_attention_kwargs"]["concat_conds"].to(sample)
            picture = torch.cat([picture] * (sample.shape[0] // picture.shape[0]), dim=0)
            kwargs["cross_attention_kwargs"] = {}
            return original_forward(torch.cat([sample, picture], dim=1), timestep,
                                    encoder_hidden_states, **kwargs)

        unet.forward = forward_with_picture

        # IC-Light ships as differences to add to the base weights.
        delta = safetensors.torch.load_file(str(offsets / OFFSETS_FILE))
        base_weights = unet.state_dict()
        merged = {key: base_weights[key] + delta[key].to(base_weights[key]) for key in base_weights}
        unet.load_state_dict(merged, strict=True)
        del delta, base_weights, merged

        scheduler = DPMSolverMultistepScheduler(
            num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012,
            algorithm_type="sde-dpmsolver++", use_karras_sigmas=True, steps_offset=1,
        )
        pipeline_class: Any = StableDiffusionImg2ImgPipeline  # its typing is incomplete
        pipe = pipeline_class(
            vae=vae.to(dtype=dtype), text_encoder=text_encoder.to(dtype=dtype),
            tokenizer=tokenizer, unet=unet.to(dtype=dtype), scheduler=scheduler,
            safety_checker=None, requires_safety_checker=False, feature_extractor=None,
            image_encoder=None,
        )
        pipe.set_progress_bar_config(disable=True)
        if device.type == "cuda":
            # 6 GB cards: tile the VAE and keep only the part that is working on the
            # GPU. Attention is left to PyTorch's own memory-efficient kernel: sliced
            # attention builds the full attention matrix piece by piece, which at the
            # high-resolution size filled the card and took 4.6 s a step (RTX 4050).
            pipe.vae.enable_tiling()
            if low_memory:
                pipe.enable_attention_slicing()
                pipe.enable_sequential_cpu_offload()
            else:
                pipe.enable_model_cpu_offload()
        else:
            pipe.to(device)
        self._pipe = pipe

    def unload(self) -> None:
        self._pipe = None
        release_memory()

    def _encode(self, image: Image.Image) -> torch.Tensor:
        vae = self._pipe.vae
        pixels = _to_tensor(image).to(device=self.device, dtype=self.dtype)
        latent: torch.Tensor = vae.encode(pixels).latent_dist.mode() * vae.config.scaling_factor
        return latent

    def _decode(self, latents: torch.Tensor) -> Image.Image:
        vae = self._pipe.vae
        return _to_image(vae.decode(latents.to(self.dtype) / vae.config.scaling_factor).sample)

    def _denoise(self, start: torch.Tensor, picture: torch.Tensor, strength: float,
                 params: RelightParams, generator: torch.Generator,
                 on_step: Callable[[], None]) -> torch.Tensor:
        def callback(_pipe: Any, _step: int, _timestep: Any, state: dict[str, Any]) -> Any:
            on_step()  # may raise to cancel
            return state

        result: torch.Tensor = self._pipe(
            image=start,
            strength=strength,
            prompt=f"{params.prompt}, {QUALITY_PROMPT}",
            negative_prompt=NEGATIVE_PROMPT,
            num_inference_steps=int(round(params.steps / strength)),
            guidance_scale=params.guidance,
            generator=generator,
            output_type="latent",
            cross_attention_kwargs={"concat_conds": picture},
            callback_on_step_end=callback,
        ).images
        return result

    def total_steps(self, params: RelightParams) -> int:
        """Denoising steps a relight() call will run, for progress reporting."""
        return params.steps * (2 if params.highres else 1)

    @torch.inference_mode()
    def relight(self, picture: Image.Image, hint: Image.Image, params: RelightParams,
                on_step: Callable[[], None]) -> Image.Image:
        """Relight `picture` following `hint` (same size, sides multiples of 64)."""
        generator = torch.Generator(device="cpu").manual_seed(params.seed)
        latents = self._denoise(self._encode(hint), self._encode(picture), params.denoise,
                                params, generator, on_step)
        if not params.highres:
            return self._decode(latents)

        size = (round64(picture.width * params.highres_scale),
                round64(picture.height * params.highres_scale))
        larger = self._decode(latents).resize(size, Image.Resampling.LANCZOS)
        picture_large = picture.resize(size, Image.Resampling.LANCZOS)
        latents = self._denoise(self._encode(larger), self._encode(picture_large),
                                params.highres_denoise, params, generator, on_step)
        return self._decode(latents)
