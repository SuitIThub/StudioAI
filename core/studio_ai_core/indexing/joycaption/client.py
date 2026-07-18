"""JoyCaption client – optional torch/transformers (pip install studio-ai[vision])."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

from studio_ai_core.indexing.joycaption.presets import (
    DEFAULT_SYSTEM_PROMPT,
    get_preset,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "fancyfeast/llama-joycaption-beta-one-hf-llava"
QuantMode = Literal["bf16", "8bit", "nf4"]
# Downscale before VLM – large PNGs barely help pose captions but cost time
DEFAULT_MAX_IMAGE_EDGE = 768


class JoyCaptionUnavailable(RuntimeError):
    """Raised when vision extras are missing or model not loaded."""


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        from studio_ai_core import REPO_ROOT

        load_dotenv(REPO_ROOT / ".env", override=False)
    except Exception:
        pass


class JoyCaptionClient:
    """Thin wrapper around Llava JoyCaption. Lazy-imports heavy deps."""

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None
        self.quant: QuantMode | None = None
        self.device: str = "cpu"

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _import_torch(self):
        try:
            import torch
            from PIL import Image  # noqa: F401
            from transformers import AutoProcessor, BitsAndBytesConfig, LlavaForConditionalGeneration
        except ImportError as exc:
            raise JoyCaptionUnavailable(
                "JoyCaption requires optional deps. Install with: pip install -e \".[vision]\""
            ) from exc
        return torch, AutoProcessor, BitsAndBytesConfig, LlavaForConditionalGeneration

    def load(self, quant: QuantMode | None = None) -> str:
        _load_dotenv()
        torch, AutoProcessor, BitsAndBytesConfig, LlavaForConditionalGeneration = self._import_torch()
        if not torch.cuda.is_available():
            raise JoyCaptionUnavailable(
                "PyTorch has no CUDA (got CPU-only build). "
                "RTX 50xx needs: pip install torch torchvision "
                "--index-url https://download.pytorch.org/whl/cu128 "
                f"(current: {getattr(torch, '__version__', '?')})"
            )
        q: QuantMode = quant or recommended_quant()
        if self._model is not None and self.quant == q:
            return f"JoyCaption already loaded ({q})"

        self.unload()
        self.device = "cuda"
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        hf_kwargs = {"token": token} if token else {}

        logger.info("Loading JoyCaption (%s) on %s …", q, torch.cuda.get_device_name(0))
        self._processor = AutoProcessor.from_pretrained(MODEL_NAME, **hf_kwargs)
        if self._processor.tokenizer.pad_token is None:
            self._processor.tokenizer.pad_token = self._processor.tokenizer.eos_token

        if q == "bf16":
            self._model = LlavaForConditionalGeneration.from_pretrained(
                MODEL_NAME, torch_dtype=torch.bfloat16, device_map=0, **hf_kwargs
            )
        elif q == "8bit":
            cfg = BitsAndBytesConfig(
                load_in_8bit=True,
                llm_int8_skip_modules=["vision_tower", "multi_modal_projector"],
            )
            self._model = LlavaForConditionalGeneration.from_pretrained(
                MODEL_NAME,
                torch_dtype="auto",
                device_map=0,
                quantization_config=cfg,
                **hf_kwargs,
            )
        else:
            cfg = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                llm_int8_skip_modules=["vision_tower", "multi_modal_projector"],
            )
            self._model = LlavaForConditionalGeneration.from_pretrained(
                MODEL_NAME,
                torch_dtype="auto",
                device_map=0,
                quantization_config=cfg,
                **hf_kwargs,
            )

        self._model.eval()
        self.quant = q
        logger.info("JoyCaption ready (%s) on %s", q, torch.cuda.get_device_name(0))
        return f"JoyCaption loaded ({q}) on {torch.cuda.get_device_name(0)}"

    def unload(self) -> None:
        self._model = None
        self.quant = None
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    @staticmethod
    def _resize(image: Any, max_edge: int = DEFAULT_MAX_IMAGE_EDGE) -> Any:
        w, h = image.size
        edge = max(w, h)
        if edge <= max_edge:
            return image
        scale = max_edge / float(edge)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        return image.resize((nw, nh))

    def caption_path(
        self,
        image_path: Path | str,
        *,
        caption_type: str | None = None,
        instruction: str | None = None,
        temperature: float | None = None,
        top_p: float = 0.9,
        max_new_tokens: int | None = None,
        max_image_edge: int = DEFAULT_MAX_IMAGE_EDGE,
    ) -> str:
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        img = self._resize(img, max_image_edge)
        preset = get_preset(caption_type)
        prompt = preset.user_prompt
        if instruction and instruction.strip():
            prompt = f"{prompt.rstrip()}\n\nAdditional instruction: {instruction.strip()}"
        return self.caption_image(
            img,
            caption_type=caption_type,
            prompt=prompt,
            temperature=temperature,
            top_p=top_p,
            max_new_tokens=max_new_tokens,
        )

    def caption_image(
        self,
        image: Any,
        *,
        caption_type: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        top_p: float = 0.9,
        max_new_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> str:
        import torch

        if self._model is None or self._processor is None:
            raise JoyCaptionUnavailable("JoyCaption is not loaded. Call load() first.")

        preset = get_preset(caption_type)
        text_prompt = prompt or preset.user_prompt
        sys_prompt = system_prompt or preset.system_prompt
        temp = preset.temperature if temperature is None else temperature
        tokens = preset.max_new_tokens if max_new_tokens is None else max_new_tokens

        image = image.convert("RGB")
        convo = [
            {"role": "system", "content": sys_prompt or DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": text_prompt.strip()},
        ]
        convo_string = self._processor.apply_chat_template(
            convo, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(text=[convo_string], images=[image], return_tensors="pt")
        if self.device == "cuda":
            inputs = inputs.to("cuda")
            inputs["pixel_values"] = inputs["pixel_values"].to(torch.bfloat16)

        with torch.no_grad():
            generate_ids = self._model.generate(
                **inputs,
                max_new_tokens=tokens,
                do_sample=temp > 0,
                suppress_tokens=None,
                use_cache=True,
                temperature=temp if temp > 0 else None,
                top_k=None,
                top_p=top_p if temp > 0 else None,
            )[0]

        generate_ids = generate_ids[inputs["input_ids"].shape[1] :]
        caption = self._processor.tokenizer.decode(
            generate_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        return caption.strip()


def recommended_quant() -> QuantMode:
    try:
        import torch
    except ImportError:
        return "nf4"
    if not torch.cuda.is_available():
        return "nf4"
    mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    if mem_gb >= 20:
        return "bf16"
    if mem_gb >= 12:
        return "8bit"
    return "nf4"
