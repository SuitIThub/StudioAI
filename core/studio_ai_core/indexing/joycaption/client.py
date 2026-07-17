"""JoyCaption client – optional torch/transformers (pip install studio-ai[vision])."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

from studio_ai_core.indexing.joycaption.presets import DEFAULT_SYSTEM_PROMPT, prompt_for

logger = logging.getLogger(__name__)

MODEL_NAME = "fancyfeast/llama-joycaption-beta-one-hf-llava"
QuantMode = Literal["bf16", "8bit", "nf4"]


class JoyCaptionUnavailable(RuntimeError):
    """Raised when vision extras are missing or model not loaded."""


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
        torch, AutoProcessor, BitsAndBytesConfig, LlavaForConditionalGeneration = self._import_torch()
        q: QuantMode = quant or recommended_quant()
        if self._model is not None and self.quant == q:
            return f"JoyCaption already loaded ({q})"

        self.unload()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        hf_kwargs = {"token": token} if token else {}

        self._processor = AutoProcessor.from_pretrained(MODEL_NAME, **hf_kwargs)
        if self._processor.tokenizer.pad_token is None:
            self._processor.tokenizer.pad_token = self._processor.tokenizer.eos_token

        if self.device == "cpu":
            self._model = LlavaForConditionalGeneration.from_pretrained(
                MODEL_NAME,
                torch_dtype=torch.float32,
                low_cpu_mem_usage=True,
                **hf_kwargs,
            )
            self._model.eval()
            self.quant = q
            return "JoyCaption loaded on CPU (slow)"

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
        logger.info("JoyCaption loaded (%s) on %s", q, self.device)
        return f"JoyCaption loaded ({q})"

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

    def caption_path(
        self,
        image_path: Path | str,
        *,
        caption_type: str | None = None,
        temperature: float = 0.6,
        top_p: float = 0.9,
        max_new_tokens: int = 384,
    ) -> str:
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        return self.caption_image(
            img,
            caption_type=caption_type,
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
        temperature: float = 0.6,
        top_p: float = 0.9,
        max_new_tokens: int = 384,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> str:
        import torch

        if self._model is None or self._processor is None:
            raise JoyCaptionUnavailable("JoyCaption is not loaded. Call load() first.")

        text_prompt = prompt or prompt_for(caption_type)
        image = image.convert("RGB")
        convo = [
            {"role": "system", "content": system_prompt},
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
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                suppress_tokens=None,
                use_cache=True,
                temperature=temperature if temperature > 0 else None,
                top_k=None,
                top_p=top_p if temperature > 0 else None,
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
