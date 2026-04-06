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
        file_data: Dict[str, Any] = {}
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                file_data = json.load(f)

        api_key = (
            os.getenv("LLM_IMAGE_API_KEY")
            or file_data.get("image_api_key")
            or os.getenv("LLM_API_KEY")
            or file_data.get("api_key")
        )
        if not api_key:
            raise BackgroundImageConfigError(
                "未配置图片生成 API Key，请设置 LLM_IMAGE_API_KEY 或 config/llm.json 中的 image_api_key。"
            )

        base_url = (
            os.getenv("LLM_IMAGE_BASE_URL")
            or file_data.get("image_base_url")
            or os.getenv("LLM_BASE_URL")
            or file_data.get("base_url")
        )
        model = os.getenv("LLM_IMAGE_MODEL") or file_data.get("image_model") or "gpt-image-1"
        size = os.getenv("LLM_IMAGE_SIZE") or file_data.get("image_size") or "1536x1024"
        quality = os.getenv("LLM_IMAGE_QUALITY") or file_data.get("image_quality") or "medium"
        style = os.getenv("LLM_IMAGE_STYLE") or file_data.get("image_style") or "natural"
        output_format = os.getenv("LLM_IMAGE_OUTPUT_FORMAT") or file_data.get("image_output_format") or "webp"
        timeout = float(os.getenv("LLM_IMAGE_TIMEOUT") or file_data.get("image_timeout") or 120.0)
        cfg_raw = os.getenv("LLM_IMAGE_CFG") or file_data.get("image_cfg")
        cfg = float(cfg_raw) if cfg_raw is not None else 4.0

        return cls(
            api_key=api_key,
            base_url=base_url,
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
        client_kwargs = {"api_key": self.config.api_key}
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
            "请为一款克苏鲁调查题材文字冒险游戏生成网页背景图。",
            f"要求：固定 {aspect_ratio_label} 横向环境概念图，电影感构图，氛围浓厚，适合叠加文字界面，不要擅自改变画幅比例。",
            "构图要求：图像必须边到边铺满整个画幅，不要白边、黑边、相框边、纸张边、胶片边、页边距或任何形式的留白边缘。",
            "禁止：任何可读文字、汉字、英文字母、数字、水印、logo、UI、边框、分镜格、角色半身像特写、卡通风。",
            "额外限制：不要出现招牌、海报、书封标题、档案页可辨认文字、字幕、界面字样；如果画面里出现书籍、纸张、铭牌或标识，只表现材质和轮廓，不要渲染可辨认内容。",
            "画面重点：场景氛围、光影、线索感、微妙不安，而不是战斗动作。",
        ]
        if world_name:
            parts.append(f"世界：{world_name}")
        if scene_name:
            parts.append(f"当前场景：{scene_name}")
        if scene_description:
            parts.append(f"场景公开描述：{scene_description.strip()}")
        if source_text:
            parts.append(f"本轮叙事重点：{source_text.strip()}")
        parts.append("风格关键词：dark academia, occult archive, cinematic lighting, atmospheric, environmental storytelling.")
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
        metadata_path = self.cache_dir / f"{cache_key}.json"

        if image_path.exists() and not force:
            return {
                "path": str(image_path),
                "prompt": prompt,
                "cache_hit": True,
                "metadata_path": str(metadata_path),
            }

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
        }

    def build_data_uri(self, image_path: str | Path) -> str:
        path = Path(image_path)
        mime_type = self._mime_for_extension(path.suffix.lower().lstrip("."))
        return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    def _generate_image_bytes(self, prompt: str) -> bytes:
        logger.info("正在生成 AI 背景图，模型=%s", self.config.model)
        if self._is_siliconflow_endpoint():
            return self._generate_image_bytes_siliconflow(prompt)

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

        first = response.data[0] if getattr(response, "data", None) else None
        if first is None:
            raise RuntimeError("图片生成接口未返回任何图像数据。")

        b64_json = getattr(first, "b64_json", None)
        if b64_json:
            return base64.b64decode(b64_json)

        url = getattr(first, "url", None)
        if url:
            with urlopen(url, timeout=self.config.timeout) as remote:
                return remote.read()

        if isinstance(first, dict):
            if first.get("b64_json"):
                return base64.b64decode(first["b64_json"])
            if first.get("url"):
                with urlopen(first["url"], timeout=self.config.timeout) as remote:
                    return remote.read()

        raise RuntimeError("图片生成接口返回了无法识别的数据格式。")

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
            raise RuntimeError(f"SiliconFlow 图片接口返回结果缺少 url: {body}")

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
        output_format = (output_format or "webp").lower()
        if output_format in {"jpeg", "jpg"}:
            return "jpg"
        if output_format == "png":
            return "png"
        return "webp"

    @staticmethod
    def _mime_for_extension(extension: str) -> str:
        if extension == "png":
            return "image/png"
        if extension in {"jpg", "jpeg"}:
            return "image/jpeg"
        return "image/webp"
