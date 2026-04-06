from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorldBackgroundConfig:
    default_image: str
    scene_images: dict[str, str]


class WorldBackgroundResolver:
    """Resolve per-world and per-scene default background images."""

    def __init__(
        self,
        *,
        project_root: Path,
        world_root: Path,
        local_background_dir: Path,
        fallback_background_file: Path,
    ) -> None:
        self.project_root = Path(project_root)
        self.world_root = Path(world_root)
        self.local_background_dir = Path(local_background_dir)
        self.fallback_background_file = Path(fallback_background_file)
        self._cache: dict[str, tuple[float, WorldBackgroundConfig]] = {}
        self._shared_defaults = (
            "data/local_backgrounds/shared_default.png",
            "data/local_backgrounds/shared_default.jpg",
            "data/local_backgrounds/shared_default.jpeg",
            "data/local_backgrounds/shared_default.webp",
        )

    @staticmethod
    def local_image_mime(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".png":
            return "image/png"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".webp":
            return "image/webp"
        if suffix == ".svg":
            return "image/svg+xml"
        return "application/octet-stream"

    @staticmethod
    def local_background_fallback_svg() -> str:
        return """<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="1024" viewBox="0 0 1536 1024">
  <defs>
    <linearGradient id="g0" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="rgb(245,236,224)"/>
      <stop offset="55%" stop-color="rgb(232,220,204)"/>
      <stop offset="100%" stop-color="rgb(214,200,184)"/>
    </linearGradient>
    <radialGradient id="g1" cx="20%" cy="18%" r="55%">
      <stop offset="0%" stop-color="rgba(255,255,255,0.58)"/>
      <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
    </radialGradient>
    <radialGradient id="g2" cx="78%" cy="78%" r="72%">
      <stop offset="0%" stop-color="rgba(90,70,54,0.16)"/>
      <stop offset="100%" stop-color="rgba(90,70,54,0)"/>
    </radialGradient>
  </defs>
  <rect width="1536" height="1024" fill="url(#g0)"/>
  <rect width="1536" height="1024" fill="url(#g1)"/>
  <rect width="1536" height="1024" fill="url(#g2)"/>
</svg>"""

    def absolute_media_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.project_root / path

    def world_config_path(self, world: str) -> Path:
        return self.world_root / world / "world.json"

    def _fallback_default_path(self) -> str:
        return self._shared_defaults[0]

    def _load_config(self, world: str) -> WorldBackgroundConfig:
        path = self.world_config_path(world)
        if not path.exists():
            return WorldBackgroundConfig(default_image=self._fallback_default_path(), scene_images={})

        mtime = path.stat().st_mtime
        cached = self._cache.get(world)
        if cached and cached[0] == mtime:
            return cached[1]

        payload: dict[str, Any] = {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

        backgrounds = payload.get("backgrounds")
        if not isinstance(backgrounds, dict):
            backgrounds = {}

        default_image = str(backgrounds.get("default_image") or self._fallback_default_path())
        scene_images_raw = backgrounds.get("scene_images")
        scene_images: dict[str, str] = {}
        if isinstance(scene_images_raw, dict):
            for key, value in scene_images_raw.items():
                scene_id = str(key or "").strip()
                image_path = str(value or "").strip()
                if scene_id and image_path:
                    scene_images[scene_id] = image_path

        config = WorldBackgroundConfig(default_image=default_image, scene_images=scene_images)
        self._cache[world] = (mtime, config)
        return config

    def load_world_background_config(self, world: str) -> dict[str, Any]:
        config = self._load_config(world)
        return {
            "default_image": config.default_image,
            "scene_images": dict(config.scene_images),
        }

    def configured_background_missing_items(self, worlds: list[str], *, max_items: int = 6) -> tuple[list[str], int]:
        missing: list[str] = []
        seen: set[str] = set()

        for world in worlds:
            config = self._load_config(world)
            candidates: list[str] = [config.default_image, *config.scene_images.values()]
            for raw in candidates:
                if not raw:
                    continue
                resolved = self.absolute_media_path(raw)
                if resolved.exists():
                    continue
                key = f"{world}:{raw}"
                if key in seen:
                    continue
                seen.add(key)
                missing.append(key)

        total = len(missing)
        return missing[:max_items], total

    def ensure_local_fallback_background(self) -> Path:
        self.local_background_dir.mkdir(parents=True, exist_ok=True)
        if not self.fallback_background_file.exists():
            self.fallback_background_file.write_text(self.local_background_fallback_svg(), encoding="utf-8")
        return self.fallback_background_file

    def resolve_configured_scene_background_path(self, world: str, scene_id: str) -> tuple[Path, bool]:
        config = self._load_config(world)
        candidates: list[str] = []

        if scene_id and scene_id in config.scene_images:
            candidates.append(config.scene_images[scene_id])

        candidates.append(config.default_image)
        candidates.extend(self._shared_defaults)

        for raw in candidates:
            if not raw:
                continue
            resolved = self.absolute_media_path(raw)
            if resolved.exists() and resolved.is_file():
                return resolved, True

        return self.ensure_local_fallback_background(), False

    def build_local_background_data_uri(self, path: Path) -> str:
        mime = self.local_image_mime(path)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

