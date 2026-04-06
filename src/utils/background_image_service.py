from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

try:
    import certifi
except ImportError:  # pragma: no cover - optional runtime helper
    certifi = None  # type: ignore[assignment]

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency absence is handled at runtime
    OPENAI_AVAILABLE = False
    OpenAI = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class BackgroundImageConfigError(Exception):
    """Raised when background image generation is not configured correctly."""


def _load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pick(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


@dataclass
class BackgroundImageConfig:
    api_key: str
    base_url: Optional[str] = None
    model: str = "gpt-image-1"
    size: str = "1536x1024"
    quality: str = "medium"
    style: str = "natural"
    output_format: str = "webp"
    timeout: float = 120.0
    cfg: Optional[float] = 4.0

    @classmethod
    def from_sources(cls, config_path: str = "config/llm.json") -> "BackgroundImageConfig":
        path = Path(config_path)
        file_data: Dict[str, Any] = _load_json_file(path)

        dm_file_data: Dict[str, Any] = {}
        for candidate in (path.with_name("dm_lm.json"), path.with_name("dm_llm.json")):
            candidate_data = _load_json_file(candidate)
            if candidate_data:
                dm_file_data = candidate_data
                break

        api_key = _pick(
            os.getenv("LLM_IMAGE_API_KEY"),
            file_data.get("image_api_key"),
            dm_file_data.get("image_api_key"),
            os.getenv("LLM_API_KEY"),
            file_data.get("api_key"),
            dm_file_data.get("api_key"),
        )
        if not api_key:
            raise BackgroundImageConfigError("未配置图片生成 API Key，请设置 LLM_IMAGE_API_KEY 或 config/llm.json。")

        base_url = _pick(
            os.getenv("LLM_IMAGE_BASE_URL"),
            file_data.get("image_base_url"),
            dm_file_data.get("image_base_url"),
            os.getenv("LLM_BASE_URL"),
            file_data.get("base_url"),
            dm_file_data.get("base_url"),
        )

        text_model = str(_pick(file_data.get("model"), dm_file_data.get("model"), ""))
        model = str(
            _pick(
                os.getenv("LLM_IMAGE_MODEL"),
                file_data.get("image_model"),
                dm_file_data.get("image_model"),
                "gpt-image-1",
            )
        )
        if model == "gpt-image-1" and (
            "dashscope.aliyuncs.com" in str(base_url or "") or text_model.startswith("qwen")
        ):
            # DashScope + Qwen setups should default to a Qwen image model.
            model = "qwen-image"

        size = str(_pick(os.getenv("LLM_IMAGE_SIZE"), file_data.get("image_size"), dm_file_data.get("image_size"), "1536x1024"))
        quality = str(_pick(os.getenv("LLM_IMAGE_QUALITY"), file_data.get("image_quality"), dm_file_data.get("image_quality"), "medium"))
        style = str(_pick(os.getenv("LLM_IMAGE_STYLE"), file_data.get("image_style"), dm_file_data.get("image_style"), "natural"))
        output_format = str(
            _pick(
                os.getenv("LLM_IMAGE_OUTPUT_FORMAT"),
                file_data.get("image_output_format"),
                dm_file_data.get("image_output_format"),
                "png" if model.startswith("qwen") else "webp",
            )
        ).lower()

        timeout_raw = _pick(
            os.getenv("LLM_IMAGE_TIMEOUT"),
            file_data.get("image_timeout"),
            dm_file_data.get("image_timeout"),
            file_data.get("timeout"),
            dm_file_data.get("timeout"),
            120.0,
        )
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = 120.0

        cfg_raw = _pick(os.getenv("LLM_IMAGE_CFG"), file_data.get("image_cfg"), dm_file_data.get("image_cfg"))
        try:
            cfg = float(cfg_raw) if cfg_raw is not None else 4.0
        except (TypeError, ValueError):
            cfg = 4.0

        return cls(
            api_key=str(api_key),
            base_url=str(base_url) if base_url else None,
            model=model,
            size=size,
            quality=quality,
            style=style,
            output_format=output_format,
            timeout=timeout,
            cfg=cfg,
        )


class BackgroundImageService:
    """Generate and cache atmospheric background images for the Streamlit UI."""

    def __init__(
        self,
        config: Optional[BackgroundImageConfig] = None,
        config_path: str = "config/llm.json",
        cache_dir: str | Path = "data/backgrounds",
    ):
        if not OPENAI_AVAILABLE:
            raise ImportError("未安装 openai 库，无法启用 AI 背景图。")

        self.config = config or BackgroundImageConfig.from_sources(config_path=config_path)
        client_kwargs: Dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.base_url:
            client_kwargs["base_url"] = self.config.base_url
        self.client = OpenAI(**client_kwargs)

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ssl_context = self._build_ssl_context()

    def build_prompt(
        self,
        scene_name: str,
        scene_description: str,
        source_text: str,
        world_name: str = "",
    ) -> str:
        """Turn the latest story beat into a stable background-art prompt."""
        aspect_ratio_label = self.aspect_ratio_label()
        parts = [
            "为文字冒险游戏生成一张无文字背景图。",
            f"画幅比例必须是 {aspect_ratio_label} 横向。",
            "要求：电影感、环境叙事、光影层次、氛围压抑或神秘。",
            "禁止：任何可读文字、水印、边框、UI元素。",
            "请做可铺满页面的完整构图，不要留白。",
        ]
        if world_name:
            parts.append(f"世界：{world_name}")
        if scene_name:
            parts.append(f"当前场景：{scene_name}")
        if scene_description:
            parts.append(f"场景描述：{scene_description.strip()}")
        if source_text:
            parts.append(f"本轮叙事要点：{source_text.strip()}")
        parts.append("风格关键词：atmospheric, cinematic lighting, environmental storytelling")
        return "\n".join(parts)

    def aspect_ratio_pair(self) -> tuple[int, int]:
        raw_size = (self.config.size or "").lower().strip()
        if "x" not in raw_size:
            return (3, 2)
        width_raw, height_raw = raw_size.split("x", maxsplit=1)
        try:
            width = int(width_raw)
            height = int(height_raw)
        except ValueError:
            return (3, 2)
        if width <= 0 or height <= 0:
            return (3, 2)
        divisor = math.gcd(width, height) or 1
        return (width // divisor, height // divisor)

    def aspect_ratio_css(self) -> str:
        width, height = self.aspect_ratio_pair()
        return f"{width} / {height}"

    def aspect_ratio_label(self) -> str:
        width, height = self.aspect_ratio_pair()
        return f"{width}:{height}"

    def build_source_signature(
        self,
        scene_name: str,
        scene_description: str,
        source_text: str,
        world_name: str = "",
    ) -> str:
        payload = "\n".join(
            [
                world_name.strip(),
                scene_name.strip(),
                scene_description.strip(),
                source_text.strip(),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def build_cache_key(self, prompt: str) -> str:
        payload = "|".join(
            [
                self.config.model,
                self.config.size,
                self.config.quality,
                self.config.style,
                self.config.output_format,
                prompt,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def generate_background(
        self,
        *,
        scene_name: str,
        scene_description: str,
        source_text: str,
        world_name: str = "",
        force: bool = False,
    ) -> Dict[str, Any]:
        prompt = self.build_prompt(
            scene_name=scene_name,
            scene_description=scene_description,
            source_text=source_text,
            world_name=world_name,
        )
        cache_key = self.build_cache_key(prompt)
        extension = self._extension_for_format(self.config.output_format)
        image_path = self.cache_dir / f"{cache_key}.{extension}"
        fallback_path = self.cache_dir / f"{cache_key}.svg"
        metadata_path = self.cache_dir / f"{cache_key}.json"

        if image_path.exists() and not force:
            return {
                "path": str(image_path),
                "prompt": prompt,
                "cache_hit": True,
                "metadata_path": str(metadata_path),
                "fallback": False,
            }

        if fallback_path.exists() and not force:
            return {
                "path": str(fallback_path),
                "prompt": prompt,
                "cache_hit": True,
                "metadata_path": str(metadata_path),
                "fallback": True,
            }

        try:
            image_bytes = self._generate_image_bytes(prompt)
            image_path.write_bytes(image_bytes)
            metadata_path.write_text(
                json.dumps(
                    {
                        "scene_name": scene_name,
                        "scene_description": scene_description,
                        "source_text": source_text,
                        "world_name": world_name,
                        "prompt": prompt,
                        "model": self.config.model,
                        "size": self.config.size,
                        "fallback": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return {
                "path": str(image_path),
                "prompt": prompt,
                "cache_hit": False,
                "metadata_path": str(metadata_path),
                "fallback": False,
            }
        except Exception as exc:
            # Keep the game usable when remote image APIs are unavailable.
            logger.warning("Background image remote generation failed; using local fallback: %s", exc)
            fallback_svg = self._build_fallback_svg(seed=cache_key)
            fallback_path.write_text(fallback_svg, encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "scene_name": scene_name,
                        "scene_description": scene_description,
                        "source_text": source_text,
                        "world_name": world_name,
                        "prompt": prompt,
                        "model": self.config.model,
                        "size": self.config.size,
                        "fallback": True,
                        "fallback_reason": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return {
                "path": str(fallback_path),
                "prompt": prompt,
                "cache_hit": False,
                "metadata_path": str(metadata_path),
                "fallback": True,
                "fallback_reason": str(exc),
            }

    def build_data_uri(self, image_path: str | Path) -> str:
        path = Path(image_path)
        mime_type = self._mime_for_extension(path.suffix.lower().lstrip("."))
        return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    def _generate_image_bytes(self, prompt: str) -> bytes:
        logger.info("Generating background image with model=%s", self.config.model)

        if self._is_siliconflow_endpoint():
            return self._generate_image_bytes_siliconflow(prompt)

        # First attempt: OpenAI-compatible full argument set.
        try:
            response = self.client.images.generate(
                prompt=prompt,
                model=self.config.model,
                size=self.config.size,
                quality=self.config.quality,
                style=self.config.style,
                output_format=self.config.output_format,
                response_format="b64_json",
                timeout=self.config.timeout,
            )
        except TypeError:
            # Provider SDK shape mismatch: retry with a minimal compatible payload.
            response = self.client.images.generate(
                prompt=prompt,
                model=self.config.model,
                size=self.config.size,
                timeout=self.config.timeout,
            )
        except Exception:
            # Provider may reject optional arguments; retry once with minimal payload.
            response = self.client.images.generate(
                prompt=prompt,
                model=self.config.model,
                size=self.config.size,
                timeout=self.config.timeout,
            )

        first = None
        if getattr(response, "data", None):
            first = response.data[0]
        elif isinstance(response, dict) and response.get("data"):
            first = response["data"][0]

        if first is None:
            raise RuntimeError("图片生成接口未返回任何图像数据。")

        b64_json = getattr(first, "b64_json", None)
        if b64_json:
            return base64.b64decode(b64_json)

        url = getattr(first, "url", None)
        if url:
            with urlopen(url, timeout=self.config.timeout, context=self.ssl_context) as remote:
                return remote.read()

        if isinstance(first, dict):
            if first.get("b64_json"):
                return base64.b64decode(first["b64_json"])
            if first.get("url"):
                with urlopen(first["url"], timeout=self.config.timeout, context=self.ssl_context) as remote:
                    return remote.read()

        raise RuntimeError("图片生成接口返回了无法识别的结果结构。")

    def _generate_image_bytes_siliconflow(self, prompt: str) -> bytes:
        endpoint = self._siliconflow_image_endpoint()
        payload = self._build_siliconflow_payload(prompt)
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout, context=self.ssl_context) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SiliconFlow 图片请求失败: HTTP {exc.code} {detail}") from exc

        data = json.loads(body)
        images = data.get("images") or []
        if not images:
            raise RuntimeError(f"SiliconFlow 图片接口未返回 images 字段: {body}")

        first = images[0]
        url = first.get("url") if isinstance(first, dict) else None
        if not url:
            raise RuntimeError(f"SiliconFlow 图片接口结果缺少 url: {body}")

        with urlopen(url, timeout=self.config.timeout, context=self.ssl_context) as remote:
            return remote.read()

    def _is_siliconflow_endpoint(self) -> bool:
        return "api.siliconflow.cn" in (self.config.base_url or "")

    def _siliconflow_image_endpoint(self) -> str:
        base = (self.config.base_url or "").rstrip("/")
        if not base:
            raise RuntimeError("未配置 SiliconFlow 图片接口 base_url。")
        if base.endswith("/images/generations"):
            return base
        return f"{base}/images/generations"

    def _build_siliconflow_payload(self, prompt: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
        }

        if not self.config.model.startswith("Qwen/Qwen-Image-Edit"):
            payload["image_size"] = self.config.size

        if self.config.model.startswith("Qwen/") and self.config.cfg is not None:
            payload["cfg"] = self.config.cfg

        return payload

    @staticmethod
    def _build_ssl_context() -> ssl.SSLContext:
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()

    @staticmethod
    def _extension_for_format(output_format: str) -> str:
        normalized = (output_format or "webp").lower().strip()
        if normalized in {"jpeg", "jpg"}:
            return "jpg"
        if normalized == "png":
            return "png"
        return "webp"

    @staticmethod
    def _mime_for_extension(extension: str) -> str:
        if extension == "svg":
            return "image/svg+xml"
        if extension == "png":
            return "image/png"
        if extension in {"jpg", "jpeg"}:
            return "image/jpeg"
        return "image/webp"

    @staticmethod
    def _build_fallback_svg(seed: str) -> str:
        """Generate a deterministic no-text atmospheric SVG background."""
        s = (seed or "0" * 16).lower()
        base = int(s[:8], 16)

        def channel(offset: int, minimum: int, maximum: int) -> int:
            span = maximum - minimum
            return minimum + ((base >> offset) & 0xFF) % (span + 1)

        c1 = (channel(0, 35, 95), channel(8, 28, 78), channel(16, 24, 72))
        c2 = (channel(4, 76, 150), channel(12, 60, 128), channel(20, 44, 110))
        c3 = (channel(2, 120, 190), channel(10, 98, 166), channel(18, 76, 148))

        return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1536\" height=\"1024\" viewBox=\"0 0 1536 1024\">\n  <defs>\n    <linearGradient id=\"g0\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">\n      <stop offset=\"0%\" stop-color=\"rgb({c1[0]},{c1[1]},{c1[2]})\"/>\n      <stop offset=\"55%\" stop-color=\"rgb({c2[0]},{c2[1]},{c2[2]})\"/>\n      <stop offset=\"100%\" stop-color=\"rgb({c3[0]},{c3[1]},{c3[2]})\"/>\n    </linearGradient>\n    <radialGradient id=\"g1\" cx=\"20%\" cy=\"15%\" r=\"60%\">\n      <stop offset=\"0%\" stop-color=\"rgba(255,240,215,0.26)\"/>\n      <stop offset=\"100%\" stop-color=\"rgba(255,240,215,0)\"/>\n    </radialGradient>\n    <radialGradient id=\"g2\" cx=\"80%\" cy=\"85%\" r=\"70%\">\n      <stop offset=\"0%\" stop-color=\"rgba(20,16,14,0.28)\"/>\n      <stop offset=\"100%\" stop-color=\"rgba(20,16,14,0)\"/>\n    </radialGradient>\n  </defs>\n  <rect width=\"1536\" height=\"1024\" fill=\"url(#g0)\"/>\n  <rect width=\"1536\" height=\"1024\" fill=\"url(#g1)\"/>\n  <rect width=\"1536\" height=\"1024\" fill=\"url(#g2)\"/>\n  <ellipse cx=\"420\" cy=\"330\" rx=\"320\" ry=\"210\" fill=\"rgba(255,255,255,0.06)\"/>\n  <ellipse cx=\"1180\" cy=\"700\" rx=\"360\" ry=\"260\" fill=\"rgba(0,0,0,0.10)\"/>\n</svg>"""
