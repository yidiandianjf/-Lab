from __future__ import annotations

import html
import logging
import re
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Streamlit hot-reload can occasionally leave a non-package "src" module in memory
# on Python 3.13, which breaks nested imports like src.rule.rule_system.
_src_mod = sys.modules.get("src")
if _src_mod is not None and not hasattr(_src_mod, "__path__"):
    del sys.modules["src"]

from src.main import initialize_game
from src.utils.world_background_resolver import WorldBackgroundResolver
try:
    from src.utils.background_image_service import BackgroundImageService, BackgroundImageConfigError
    _BACKGROUND_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - optional dependency path
    BackgroundImageService = None  # type: ignore[assignment]

    class BackgroundImageConfigError(Exception):
        pass

    _BACKGROUND_IMPORT_ERROR = str(exc)


APP_TITLE = "调查档案室"
DEFAULT_WORLD = "mysterious_library"
DEFAULT_SAVE = "auto_save"
WORLD_ROOT = ROOT / "config" / "world"
DEFAULT_DB = ROOT / "data" / "game.db"
SAVE_ROOT = ROOT / "data" / "saves"
BACKGROUND_CACHE_DIR = ROOT / "data" / "backgrounds"
LOCAL_BACKGROUND_DIR = ROOT / "data" / "local_backgrounds"
LOCAL_FALLBACK_BACKGROUND_FILE = LOCAL_BACKGROUND_DIR / "_fallback_default.svg"

WORLD_LABELS = {
    "mysterious_library": "COC",
    "daiyu_enters_jia": "林黛玉进贾府",
    "sanguo_mao_lu": "三顾茅庐",
}
ALLOWED_WORLDS = ["mysterious_library", "daiyu_enters_jia", "sanguo_mao_lu"]

BACKGROUND_RESOLVER = WorldBackgroundResolver(
    project_root=ROOT,
    world_root=WORLD_ROOT,
    local_background_dir=LOCAL_BACKGROUND_DIR,
    fallback_background_file=LOCAL_FALLBACK_BACKGROUND_FILE,
)

_BACKGROUND_SERVICE: Any = None
_BACKGROUND_SERVICE_ERROR: str | None = None

MOVE_INTENT_TOKENS = (
    "去",
    "前往",
    "前去",
    "走向",
    "走到",
    "进入",
    "赶往",
    "移动",
    "出发",
    "往",
    "朝",
    "向",
)

DIRECTION_ALIASES = {
    "东": {"东", "东边", "东方", "向东", "往东", "朝东", "east", "e"},
    "西": {"西", "西边", "西方", "向西", "往西", "朝西", "west", "w"},
    "南": {"南", "南边", "南方", "向南", "往南", "朝南", "south", "s"},
    "北": {"北", "北边", "北方", "向北", "往北", "朝北", "north", "n"},
    "东北": {"东北", "东北方", "向东北", "往东北", "朝东北", "northeast", "ne"},
    "东南": {"东南", "东南方", "向东南", "往东南", "朝东南", "southeast", "se"},
    "西北": {"西北", "西北方", "向西北", "往西北", "朝西北", "northwest", "nw"},
    "西南": {"西南", "西南方", "向西南", "往西南", "朝西南", "southwest", "sw"},
    "上": {"上", "向上", "往上", "朝上", "up", "u"},
    "下": {"下", "向下", "往下", "朝下", "down", "d"},
    "里": {"里", "向里", "往里", "朝里", "内", "向内", "inside", "in"},
    "外": {"外", "向外", "往外", "朝外", "outside", "out"},
    "前": {"前", "向前", "往前", "朝前", "forward", "f"},
    "后": {"后", "向后", "往后", "朝后", "back", "backward", "b"},
}

DIRECTION_ALIAS_TO_CANONICAL = {
    alias: canonical
    for canonical, aliases in DIRECTION_ALIASES.items()
    for alias in aliases
}

st.set_page_config(
    page_title=APP_TITLE,
    layout="wide",
)


# 璇诲彇鍙敤涓栫晫鐩綍锛屼緵渚ц竟鏍忎笅鎷夋閫夋嫨銆?
def list_worlds() -> list[str]:
    existing = {path.name for path in WORLD_ROOT.iterdir() if path.is_dir()} if WORLD_ROOT.exists() else set()
    worlds = [world for world in ALLOWED_WORLDS if world in existing]
    return worlds or ([DEFAULT_WORLD] if DEFAULT_WORLD in existing else list(ALLOWED_WORLDS))


def world_label(world: str) -> str:
    return WORLD_LABELS.get(world, world)


def list_saves() -> list[str]:
    if not SAVE_ROOT.exists():
        return []
    saves = [path.stem for path in SAVE_ROOT.glob("*.json") if path.is_file()]
    return sorted(set(saves))


def build_args(world: str, load_name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        db=str(DEFAULT_DB),
        mode="sqlite",
        load=load_name,
        world=world,
        name=None,
    )


# 鐩存帴璋冪敤鍘熼」鐩殑 initialize_game锛岃€屼笉鏄湪鍓嶇閲嶅瀹炵幇寮曟搸鍒涘缓閫昏緫銆?
def create_engine(world: str, load_name: str | None = None):
    logging.getLogger().setLevel(logging.INFO)
    return initialize_game(build_args(world=world, load_name=load_name))


# 姣忔鏂板紑灞€鎴栬妗ｆ椂锛岄噸寤哄紩鎿庡苟鍒锋柊褰撳墠浼氳瘽鐘舵€併€?
def bootstrap_session(world: str, load_name: str | None = None) -> None:
    engine = create_engine(world=world, load_name=load_name)
    state = engine.get_game_state()
    scene = state.get_current_map()
    opening = (
        f"会话已就绪。当前世界：{world_label(world)}。"
        if load_name
        else f"新游戏已开始。当前世界：{world_label(world)}。"
    )
    if scene:
        opening += f" 你现在位于《{scene.name}》。"

    st.session_state.engine = engine
    st.session_state.feed = [
        {
            "role": "assistant",
            "kind": "system",
            "content": opening,
        }
    ]
    st.session_state.last_check = None
    st.session_state.selected_world = world
    st.session_state._save_name = load_name or DEFAULT_SAVE
    st.session_state.background_enabled = False
    st.session_state.background_auto_update = False
    st.session_state.background_image_uri = None
    st.session_state.background_image_path = None
    st.session_state.background_prompt = ""
    st.session_state.background_source_signature = ""
    st.session_state.background_source_text = ""
    st.session_state.background_status = "已使用本地默认背景。"
    st.session_state.background_error = ""
    st.session_state.background_manual_clear = False
    st.session_state.background_aspect_ratio = "3 / 2"
    st.session_state.right_sidebar_open = False
    st.session_state.story_log_open = False
    st.session_state.turn_in_progress = False
    st.session_state.last_turn_input = ""
    st.session_state.last_turn_marker = None

    apply_default_local_background(world, str(getattr(scene, "id", "") or ""))


def ensure_session() -> None:
    if "engine" not in st.session_state:
        bootstrap_session(DEFAULT_WORLD)
    if "selected_world" not in st.session_state:
        st.session_state.selected_world = DEFAULT_WORLD
    if "_save_name" not in st.session_state:
        st.session_state._save_name = DEFAULT_SAVE
    if "feed" not in st.session_state:
        st.session_state.feed = []
    if "last_check" not in st.session_state:
        st.session_state.last_check = None
    if "background_enabled" not in st.session_state:
        st.session_state.background_enabled = False
    if "background_auto_update" not in st.session_state:
        st.session_state.background_auto_update = False
    if "background_image_uri" not in st.session_state:
        st.session_state.background_image_uri = None
    if "background_image_path" not in st.session_state:
        st.session_state.background_image_path = None
    if "background_prompt" not in st.session_state:
        st.session_state.background_prompt = ""
    if "background_status" not in st.session_state:
        st.session_state.background_status = "已使用本地默认背景。"
    if "background_error" not in st.session_state:
        st.session_state.background_error = ""
    if "background_source_signature" not in st.session_state:
        st.session_state.background_source_signature = ""
    if "background_source_text" not in st.session_state:
        st.session_state.background_source_text = ""
    if "background_manual_clear" not in st.session_state:
        st.session_state.background_manual_clear = False
    if "background_aspect_ratio" not in st.session_state:
        st.session_state.background_aspect_ratio = "3 / 2"
    if "right_sidebar_open" not in st.session_state:
        st.session_state.right_sidebar_open = False
    if "story_log_open" not in st.session_state:
        st.session_state.story_log_open = False
    if "action_input_value" not in st.session_state:
        st.session_state.action_input_value = ""
    if "turn_in_progress" not in st.session_state:
        st.session_state.turn_in_progress = False
    if "last_turn_input" not in st.session_state:
        st.session_state.last_turn_input = ""
    if "last_turn_marker" not in st.session_state:
        st.session_state.last_turn_marker = None

    if not st.session_state.get("background_image_uri"):
        apply_default_local_background(
            active_world_name(),
            current_scene_id(),
        )
    else:
        sync_scene_background_if_needed(force=False)


def startup_warnings() -> list[str]:
    warnings: list[str] = []
    if _BACKGROUND_IMPORT_ERROR:
        warnings.append(f"背景图模块未成功加载，已自动降级。原因：{_BACKGROUND_IMPORT_ERROR}")
    if not DEFAULT_DB.exists():
        warnings.append(f"默认数据库不存在：{DEFAULT_DB}")
    missing_preview, missing_total = configured_background_missing_items()
    if missing_total > 0:
        preview_text = "；".join(missing_preview)
        suffix = f"；另有 {missing_total - len(missing_preview)} 项未列出" if missing_total > len(missing_preview) else ""
        warnings.append(f"部分场景默认背景图文件缺失：{preview_text}{suffix}")
    return warnings


def get_runtime_control_status() -> dict[str, str]:
    engine = st.session_state.engine
    ai_status_text = "未知"
    speed_mode_text = "未知"

    if hasattr(engine, "get_ai_screening_status"):
        try:
            ai_status = engine.get_ai_screening_status() or {}
            enabled_text = "开启" if ai_status.get("enabled") else "关闭"
            configured_text = "已配置" if ai_status.get("configured") else "未配置"
            available_text = "可用" if ai_status.get("available") else "不可用"
            ai_status_text = f"{enabled_text}（{configured_text}/{available_text}）"
        except Exception:
            ai_status_text = "获取失败"

    if hasattr(engine, "get_speed_mode"):
        try:
            speed_mode_text = str(engine.get_speed_mode() or "unknown")
        except Exception:
            speed_mode_text = "获取失败"

    return {
        "ai_screening": ai_status_text,
        "speed_mode": speed_mode_text,
    }


def format_text(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


def render_html(markup: str) -> None:
    """Render HTML safely without markdown code-block indentation issues."""
    normalized = textwrap.dedent(markup)
    # Remove leading spaces on every line to avoid markdown interpreting HTML as code blocks.
    normalized = "\n".join(line.lstrip() for line in normalized.splitlines())
    st.markdown(normalized.strip(), unsafe_allow_html=True)


def sanitize_display_text(text: Any) -> str:
    """Remove code-like fragments so the main panel only shows readable prose."""
    raw = str(text or "")
    sanitized = re.sub(r"```[\s\S]*?```", "", raw)
    sanitized = re.sub(r"`([^`]*)`", r"\1", sanitized)
    sanitized = re.sub(r"</?[^>\n]+>", "", sanitized)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    return sanitized or "（无可显示文本）"


def normalize_story_display_text(text: Any) -> str:
    """Keep narrative output readable: no code fragments, no abrupt English tokens, no ellipsis tail."""
    cleaned = sanitize_display_text(text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n+", "\n", cleaned).strip()

    # Remove technical/code-ish English tokens in story prose.
    cleaned = re.sub(r"\b(?:import|from|def|class|return|json|python|javascript|null|true|false|explicit)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[A-Za-z]{3,}\b", "", cleaned)

    # Remove residual code punctuation noise.
    cleaned = re.sub(r"[{}<>$#_`~^|]+", "", cleaned)
    cleaned = re.sub(r"\([^)\n]{1,24}\)", "", cleaned)

    # No trailing ellipsis; end with full sentence punctuation.
    cleaned = re.sub(r"\.{3,}", "。", cleaned)
    cleaned = cleaned.replace("…", "。")
    cleaned = re.sub(r"([。！？]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned).strip()

    # Remove non-Chinese/code-like orphan lines.
    kept_lines: list[str] = []
    for line in cleaned.split("\n"):
        line = line.strip()
        if not line:
            continue
        if not re.search(r"[\u4e00-\u9fff]", line):
            continue
        kept_lines.append(line)
    cleaned = "\n".join(kept_lines).strip()

    if not cleaned:
        return "剧情继续推进。"
    if cleaned[-1] not in "。！？":
        cleaned = f"{cleaned}。"
    return cleaned


def local_image_mime(path: Path) -> str:
    return BACKGROUND_RESOLVER.local_image_mime(path)


def local_background_fallback_svg() -> str:
    return BACKGROUND_RESOLVER.local_background_fallback_svg()


def world_config_path(world: str) -> Path:
    return BACKGROUND_RESOLVER.world_config_path(world)


def load_world_background_config(world: str) -> dict[str, Any]:
    return BACKGROUND_RESOLVER.load_world_background_config(world)


def absolute_media_path(raw_path: str) -> Path:
    return BACKGROUND_RESOLVER.absolute_media_path(raw_path)


def configured_background_missing_items(max_items: int = 6) -> tuple[list[str], int]:
    return BACKGROUND_RESOLVER.configured_background_missing_items(list_worlds(), max_items=max_items)


def current_scene_id() -> str:
    try:
        state = st.session_state.engine.get_game_state()
        scene = state.get_current_map()
        if scene and getattr(scene, "id", None):
            return str(scene.id)
    except Exception:
        pass
    return ""


def active_world_name() -> str:
    try:
        engine = st.session_state.get("engine")
        world_name = str(getattr(engine, "world_name", "") or "").strip()
        if world_name:
            return world_name
    except Exception:
        pass
    return str(st.session_state.get("selected_world", DEFAULT_WORLD) or DEFAULT_WORLD)


def ensure_local_fallback_background() -> Path:
    return BACKGROUND_RESOLVER.ensure_local_fallback_background()


def resolve_configured_scene_background_path(world: str, scene_id: str) -> tuple[Path, bool]:
    return BACKGROUND_RESOLVER.resolve_configured_scene_background_path(world, scene_id)


def default_local_background_path(world: str, scene_id: str = "") -> tuple[Path, bool]:
    return resolve_configured_scene_background_path(world=world, scene_id=scene_id)


def build_local_background_data_uri(path: Path) -> str:
    return BACKGROUND_RESOLVER.build_local_background_data_uri(path)


def apply_default_local_background(world: str, scene_id: str = "", *, status_text: str | None = None) -> None:
    path, configured = default_local_background_path(world, scene_id)
    st.session_state.background_image_path = str(path)
    st.session_state.background_image_uri = build_local_background_data_uri(path)
    st.session_state.background_prompt = ""
    st.session_state.background_source_signature = ""
    st.session_state.background_source_text = ""
    st.session_state.background_manual_clear = False
    st.session_state.background_error = ""

    if status_text:
        st.session_state.background_status = status_text
    elif configured:
        if scene_id:
            st.session_state.background_status = f"已加载场景默认背景：{scene_id}"
        else:
            st.session_state.background_status = "已加载世界默认背景。"
    else:
        st.session_state.background_status = "背景配置图片未找到，已使用本地占位背景。"


def sync_scene_background_if_needed(force: bool = False) -> None:
    if st.session_state.get("background_enabled", False):
        return

    world = active_world_name()
    scene_id = current_scene_id()
    path, _ = default_local_background_path(world, scene_id)
    previous = str(st.session_state.get("background_image_path") or "")
    if not force and previous == str(path):
        return
    apply_default_local_background(world, scene_id)


def on_background_enabled_toggle() -> None:
    enabled = bool(st.session_state.get("background_enabled", False))
    if enabled:
        st.session_state.background_status = "AI 背景图已开启。点击“刷新背景”即可生成。"
        st.session_state.background_error = ""
    else:
        st.session_state.background_auto_update = False
        world = active_world_name()
        scene_id = current_scene_id()
        apply_default_local_background(world, scene_id, status_text="AI 背景图已关闭，当前使用场景默认背景。")


def normalize_match_text(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())


def canonical_direction(text: str) -> str | None:
    compact = normalize_match_text(text)
    return DIRECTION_ALIAS_TO_CANONICAL.get(compact)


def direction_match_score(direction: str, compact_user_text: str) -> int:
    if not direction:
        return 0
    compact_direction = normalize_match_text(direction)
    if not compact_direction:
        return 0

    aliases = {compact_direction}
    canonical = canonical_direction(compact_direction)
    if canonical:
        aliases.update(normalize_match_text(alias) for alias in DIRECTION_ALIASES.get(canonical, set()))

    best = 0
    for token in aliases:
        if token and token in compact_user_text:
            best = max(best, len(token))
    return best


def resolve_natural_move_command(user_text: str, exits: list[dict[str, str]]) -> str | None:
    if not exits:
        return None

    stripped = str(user_text or "").strip()
    if not stripped or stripped.startswith("\\"):
        return None

    compact = normalize_match_text(stripped)
    if not compact:
        return None

    direct_direction = bool(canonical_direction(compact))
    has_intent = direct_direction or any(token in compact for token in MOVE_INTENT_TOKENS)
    if not has_intent:
        return None

    candidates: list[tuple[int, str]] = []
    for exit_item in exits:
        direction = str(exit_item.get("direction") or "").strip()
        description = str(exit_item.get("description") or "").strip()
        target_id = str(exit_item.get("target_id") or "").strip()
        if not direction:
            continue

        score = 0
        for field in (description, target_id):
            field_compact = normalize_match_text(field)
            if field_compact and field_compact in compact:
                score = max(score, 200 + len(field_compact))

        directional_score = direction_match_score(direction, compact)
        if directional_score:
            score = max(score, 100 + directional_score)

        if score > 0:
            candidates.append((score, direction))

    if not candidates:
        if len(exits) == 1 and has_intent:
            only_direction = str(exits[0].get("direction") or "").strip()
            return f"\\move {only_direction}" if only_direction else None
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score = candidates[0][0]
    best = [direction for score, direction in candidates if score == best_score]
    if len(best) != 1:
        return None
    return f"\\move {best[0]}"


def ai_screening_enabled() -> bool:
    engine = st.session_state.engine
    if hasattr(engine, "get_ai_screening_status"):
        try:
            status = engine.get_ai_screening_status() or {}
            return bool(status.get("enabled"))
        except Exception:
            return False
    return False


def fast_speed_enabled() -> bool:
    engine = st.session_state.engine
    if hasattr(engine, "get_speed_mode"):
        try:
            mode = str(engine.get_speed_mode() or "").strip().lower()
            return mode == "fast"
        except Exception:
            return False
    return False


def get_background_service() -> BackgroundImageService | None:
    global _BACKGROUND_SERVICE, _BACKGROUND_SERVICE_ERROR
    if BackgroundImageService is None:
        _BACKGROUND_SERVICE_ERROR = _BACKGROUND_IMPORT_ERROR or "背景图模块不可用。"
        _BACKGROUND_SERVICE = None
        return None
    if _BACKGROUND_SERVICE is not None:
        return _BACKGROUND_SERVICE

    try:
        _BACKGROUND_SERVICE = BackgroundImageService(
            config_path=str(ROOT / "config" / "llm.json"),
            cache_dir=BACKGROUND_CACHE_DIR,
        )
        _BACKGROUND_SERVICE_ERROR = None
        return _BACKGROUND_SERVICE
    except (BackgroundImageConfigError, ImportError) as exc:
        _BACKGROUND_SERVICE_ERROR = str(exc)
        _BACKGROUND_SERVICE = None
        return None
    except Exception as exc:  # pragma: no cover - defensive path
        _BACKGROUND_SERVICE_ERROR = f"图片服务初始化失败：{exc}"
        _BACKGROUND_SERVICE = None
        return None


def normalize_check_result(check_result: Any) -> dict[str, Any] | None:
    if not check_result:
        return None

    if hasattr(check_result, "model_dump"):
        data = check_result.model_dump()
    elif isinstance(check_result, dict):
        data = dict(check_result)
    else:
        data = {
            "result": getattr(check_result, "result", ""),
            "dice_roll": getattr(check_result, "dice_roll", None),
            "target_value": getattr(check_result, "target_value", None),
            "actor_value": getattr(check_result, "actor_value", None),
            "detail": getattr(check_result, "detail", ""),
        }

    result_value = data.get("result", "")
    if hasattr(result_value, "value"):
        result_value = result_value.value
    result_text = str(result_value or "未知")
    if "." in result_text:
        result_text = result_text.split(".")[-1]
    alias = {
        "CRITICAL_SUCCESS": "大成功",
        "SUCCESS": "成功",
        "FAILURE": "失败",
        "FUMBLE": "大失败",
    }
    result_text = alias.get(result_text, result_text)
    data["result_text"] = result_text
    data["result_class"] = {
        "大成功": "critical",
        "成功": "success",
        "失败": "failure",
        "大失败": "fumble",
    }.get(result_text, "neutral")
    return data


def render_chips(values: list[str], empty_text: str = "鏆傛棤") -> None:
    if not values:
        st.caption(empty_text)
        return
    chips = "".join(f'<span class="artifact-chip">{html.escape(value)}</span>' for value in values)
    st.markdown(f'<div class="artifact-chip-row">{chips}</div>', unsafe_allow_html=True)


def render_fact_grid(items: list[tuple[str, str]]) -> None:
    cards = "".join(
        (
            '<div class="fact-card">'
            f'<span class="fact-label">{html.escape(label)}</span>'
            f'<span class="fact-value">{html.escape(value)}</span>'
            "</div>"
        )
        for label, value in items
    )
    st.markdown(f'<div class="fact-grid">{cards}</div>', unsafe_allow_html=True)


# 浠庡綋鍓嶅紩鎿庨噷鎻愬彇鈥滈〉闈㈢湡姝ｅ叧蹇冪殑鏁版嵁鈥濓紝閬垮厤娓叉煋鍑芥暟鍒板鐩存帴璁块棶搴曞眰鐘舵€併€?
def visible_scene_data():
    engine = st.session_state.engine
    state = engine.get_game_state()
    player = state.get_player()
    scene = state.get_current_map()

    item_names: list[str] = []
    npc_names: list[str] = []
    exits: list[dict[str, str]] = []
    inventory_names: list[str] = []

    if player:
        for item_id in player.inventory:
            item = state.items.get(item_id)
            if item:
                inventory_names.append(item.name)

    if scene:
        for neighbor in scene.neighbors:
            exits.append(
                {
                    "direction": neighbor.direction,
                    "target_id": neighbor.id,
                    "description": neighbor.description,
                }
            )

        for item_id in scene.entities.items:
            item = state.items.get(item_id)
            if item:
                item_names.append(item.name)

        for char_id in scene.entities.characters:
            if player and char_id == player.id:
                continue
            char = state.characters.get(char_id)
            if char:
                npc_names.append(char.name)

    return state, player, scene, inventory_names, item_names, npc_names, exits


def resolve_background_context(story_text: str) -> dict[str, str]:
    _, _, scene, _, item_names, npc_names, exits = visible_scene_data()

    scene_name = scene.name if scene else "未知场景"
    scene_description = scene.description.get_public_text() if scene else ""

    details = []
    if npc_names:
        details.append(f"在场角色：{', '.join(npc_names)}")
    if item_names:
        details.append(f"可见物品：{', '.join(item_names)}")
    if exits:
        exit_summary = ", ".join(
            f"{exit_item['direction']}通往{exit_item['description'] or exit_item['target_id']}"
            for exit_item in exits
        )
        details.append(f"可用出口：{exit_summary}")

    source_text = (story_text or "").strip()
    if details:
        source_text = "\n".join([part for part in [source_text, *details] if part])
    if not source_text:
        source_text = scene_description or scene_name

    return {
        "scene_name": scene_name,
        "scene_description": scene_description,
        "source_text": source_text,
        "world_name": active_world_name(),
    }


def refresh_background_image(force: bool = False, story_text: str = "", ignore_enabled: bool = False) -> None:
    if not st.session_state.get("background_enabled", False) and not ignore_enabled:
        return

    service = get_background_service()
    if service is None:
        st.session_state.background_error = ""
        apply_default_local_background(
            active_world_name(),
            current_scene_id(),
            status_text="AI 背景图不可用，已继续使用本地默认背景。",
        )
        return
    st.session_state.background_aspect_ratio = service.aspect_ratio_css()

    context = resolve_background_context(story_text)
    signature = service.build_source_signature(**context)
    if (
        not force
        and signature == st.session_state.get("background_source_signature", "")
        and st.session_state.get("background_image_uri")
    ):
        return

    with st.spinner("正在根据当前叙事生成背景图..."):
        try:
            generated = service.generate_background(force=force, **context)
        except Exception as exc:
            st.session_state.background_error = f"背景图生成失败：{exc}"
            st.session_state.background_status = "AI 背景图生成失败，已保留上一张背景。"
            return

    st.session_state.background_image_path = generated["path"]
    st.session_state.background_image_uri = service.build_data_uri(generated["path"])
    st.session_state.background_prompt = generated["prompt"]
    st.session_state.background_source_signature = signature
    st.session_state.background_source_text = context["source_text"]
    st.session_state.background_manual_clear = False
    st.session_state.background_error = ""
    if generated.get("fallback"):
        st.session_state.background_status = (
            "图片服务暂不可用，已切换为本地氛围背景。"
            if not generated.get("cache_hit")
            else "已加载本地氛围背景缓存。"
        )
    else:
        st.session_state.background_status = (
            "背景图已从本地缓存恢复。" if generated.get("cache_hit") else "背景图已根据最新叙事更新。"
        )


def clear_background_image() -> None:
    world = active_world_name()
    apply_default_local_background(world, current_scene_id(), status_text="已恢复场景默认背景。")


def add_feed(role: str, content: str, kind: str = "text", extra: dict[str, Any] | None = None) -> None:
    if not content:
        return
    if role == "assistant":
        if kind in {"text", "narrative", "security", "ending", "error"}:
            safe_content = normalize_story_display_text(content)
        else:
            safe_content = sanitize_display_text(content)
    else:
        safe_content = str(content)
    message = {
        "role": role,
        "content": safe_content,
        "kind": kind,
    }
    if extra:
        message["extra"] = extra
    st.session_state.feed.append(message)


def normalize_turn_result(raw_result: Any) -> dict[str, Any]:
    if raw_result is None:
        return {}
    if isinstance(raw_result, dict):
        return raw_result
    if hasattr(raw_result, "model_dump"):
        try:
            dumped = raw_result.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    return {}


def handle_turn(user_input: str, display_input: str | None = None) -> None:
    engine = st.session_state.engine
    text = (user_input or "").strip()
    if not text:
        return

    _, _, _, _, _, _, exits = visible_scene_data()
    resolved_move = resolve_natural_move_command(text, exits)
    engine_input = resolved_move or text

    if st.session_state.get("turn_in_progress", False):
        return

    turn_marker = None
    try:
        turn_marker = getattr(engine.get_game_state(), "turn_count", None)
    except Exception:
        turn_marker = None

    if (
        engine_input == st.session_state.get("last_turn_input", "")
        and turn_marker is not None
        and turn_marker == st.session_state.get("last_turn_marker")
    ):
        return

    st.session_state.turn_in_progress = True
    st.session_state.last_turn_input = engine_input
    st.session_state.last_turn_marker = turn_marker

    add_feed("user", display_input or text)

    try:
        raw_result = engine.process_input(engine_input)
        result = normalize_turn_result(raw_result)
        if not result:
            add_feed("assistant", "引擎没有返回结果。", kind="error")
            return

        security_payload = result.get("frontend_payload") if isinstance(result.get("frontend_payload"), dict) else None
        is_security_block = bool(security_payload and security_payload.get("type") == "safety_block")

        if is_security_block:
            message = str(security_payload.get("user_message") or result.get("response") or "输入触发安全拦截。")
            extra = {}
            hint = security_payload.get("hint")
            if hint:
                extra["hint"] = str(hint)
            add_feed("assistant", message, kind="security", extra=extra or None)
        elif result.get("response"):
            add_feed("assistant", str(result["response"]))

        check_data = normalize_check_result(result.get("check_result"))
        if check_data:
            st.session_state.last_check = check_data
            summary = (
                f"鉴定结果：{check_data['result_text']}，"
                f"d100={check_data.get('dice_roll', '-')}"
                f" / 目标值={check_data.get('target_value', '-')}"
            )
            add_feed("assistant", summary, kind="check", extra=check_data)

        if result.get("narrative"):
            add_feed("assistant", str(result["narrative"]), kind="narrative")

        if not result.get("success", True) and not is_security_block:
            add_feed("assistant", "本回合未成功完成。", kind="error")

        if result.get("game_over"):
            ending_text = ""
            if hasattr(engine, "get_ending_text"):
                ending_text = engine.get_ending_text() or ""
            if ending_text:
                add_feed("assistant", ending_text, kind="ending")

        if st.session_state.get("background_enabled") and st.session_state.get("background_auto_update", True):
            story_seed = str(result.get("narrative") or result.get("response") or "").strip()
            refresh_background_image(force=False, story_text=story_seed)
        else:
            sync_scene_background_if_needed(force=False)

    except Exception as exc:
        add_feed("assistant", f"处理输入时发生错误：{exc}", kind="error")
    finally:
        st.session_state.turn_in_progress = False


def latest_stage_dialogue(scene_description: str) -> dict[str, str]:
    label_map = {
        "narrative": "剧情",
        "text": "当前回应",
        "check": "鉴定反馈",
        "security": "安全提示",
        "ending": "结局播报",
        "error": "系统提示",
    }
    for message in reversed(st.session_state.feed):
        if message.get("role") != "assistant":
            continue
        kind = message.get("kind", "text")
        if kind == "system":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        return {
            "kind": kind,
            "speaker": label_map.get(kind, "当前回应"),
            "content": content,
        }
    return {
        "kind": "text",
        "speaker": "场景提示",
        "content": sanitize_display_text(scene_description or "调查仍在继续。"),
    }


def inject_styles(background_image_uri: str | None = None, background_aspect_ratio: str = "3 / 2") -> None:
    _ = background_image_uri
    style_block = """
        <style>
        html, body, [class*="css"] {
            font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
        }

        .stApp {
            background:
                linear-gradient(180deg, rgba(246, 241, 233, 0.96), rgba(236, 228, 215, 0.98)),
                radial-gradient(circle at top left, rgba(146, 94, 54, 0.10), transparent 28%),
                radial-gradient(circle at top right, rgba(63, 89, 77, 0.08), transparent 24%);
        }

        .main .block-container {
            max-width: 1320px;
            padding-top: 1.1rem;
            padding-bottom: 2rem;
        }

        .stage-shell {
            position: relative;
            overflow: hidden;
            aspect-ratio: __BG_ASPECT_RATIO__;
            border-radius: 20px;
            border: 1px solid rgba(72, 52, 36, 0.26);
            box-shadow: 0 22px 48px rgba(42, 30, 20, 0.18);
            background: linear-gradient(145deg, rgba(56, 40, 28, 0.94), rgba(28, 20, 14, 0.97));
            margin-bottom: 0.9rem;
        }

        .stage-bg {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            object-position: center 42%;
            transform: scale(1.12);
            transform-origin: center center;
            filter: saturate(1.03) contrast(1.03);
        }

        .stage-fallback {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #f8ede0;
            background:
                radial-gradient(circle at top, rgba(255, 225, 189, 0.21), transparent 36%),
                linear-gradient(135deg, rgba(122, 82, 49, 0.92), rgba(51, 36, 24, 0.98));
            font-size: 1.05rem;
            letter-spacing: 0.02em;
        }

        .stage-mask {
            position: absolute;
            inset: 0;
            background:
                linear-gradient(180deg, rgba(16, 11, 8, 0.26) 0%, rgba(16, 11, 8, 0.12) 38%, rgba(16, 11, 8, 0.66) 100%);
        }

        .stage-overlay {
            position: absolute;
            inset: 0.95rem 0.95rem 0.45rem;
            z-index: 3;
            display: grid;
            grid-template-columns: minmax(240px, 1fr) minmax(300px, 1.22fr) minmax(240px, 1fr);
            grid-template-rows: auto auto 1fr auto;
            column-gap: 0.8rem;
            row-gap: 0.62rem;
            align-items: start;
        }

        .glass {
            border: 1px solid rgba(64, 47, 34, 0.28);
            border-radius: 12px;
            background: rgba(255, 249, 241, 0.84);
            backdrop-filter: blur(6px);
            padding: 0.64rem 0.8rem;
            color: #2d2219;
            box-shadow: 0 8px 18px rgba(27, 18, 12, 0.13);
        }

        .glass.alert {
            border-color: rgba(165, 44, 44, 0.40);
            background: rgba(255, 236, 234, 0.90);
        }

        .stage-card-scene {
            grid-column: 1;
            grid-row: 1;
        }

        .stage-card-exits {
            grid-column: 3;
            grid-row: 1;
        }

        .stage-card-npcs {
            grid-column: 1;
            grid-row: 2;
        }

        .stage-card-items {
            grid-column: 3;
            grid-row: 2;
        }

        .stage-card-story {
            grid-column: 1 / -1;
            grid-row: 4;
            align-self: end;
            justify-self: center;
            width: min(980px, 94%);
            max-width: 980px;
        }

        .glass h3 {
            margin: 0 0 0.3rem;
            color: #2c2118;
            font-size: 1.08rem;
        }

        .eyeline {
            margin: 0 0 0.34rem;
            color: #6a4f3b;
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }

        .scene-meta {
            margin: 0 0 0.3rem;
            color: #4f3d2e;
            font-size: 0.84rem;
        }

        .scene-text {
            margin: 0;
            line-height: 1.58;
        }

        .pill-wrap {
            display: flex;
            flex-wrap: wrap;
            gap: 0.38rem;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            border: 1px solid rgba(97, 74, 55, 0.30);
            background: rgba(255, 255, 255, 0.62);
            padding: 0.2rem 0.5rem;
            font-size: 0.84rem;
            color: #3a2d23;
        }

        .feed-shell {
            border: 1px solid rgba(85, 63, 46, 0.18);
            border-radius: 14px;
            background: rgba(255, 251, 246, 0.82);
            padding: 0.55rem 0.6rem;
        }

        div[data-testid="stChatMessage"] {
            background: rgba(255, 251, 246, 0.78);
            border: 1px solid rgba(95, 71, 52, 0.12);
            border-radius: 14px;
            padding: 0.25rem 0.45rem;
        }

        @media (max-width: 1180px) {
            .stage-overlay {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                grid-template-rows: auto auto 1fr auto;
                inset: 0.65rem;
            }

            .stage-card-scene {
                grid-column: 1;
                grid-row: 1;
            }

            .stage-card-exits {
                grid-column: 2;
                grid-row: 1;
            }

            .stage-card-npcs {
                grid-column: 1;
                grid-row: 2;
            }

            .stage-card-items {
                grid-column: 2;
                grid-row: 2;
            }

            .stage-card-story {
                grid-column: 1 / -1;
                grid-row: 4;
                width: 100%;
                max-width: none;
            }
        }

        @media (max-width: 920px) {
            .stage-overlay {
                grid-template-columns: 1fr;
                grid-template-rows: auto auto auto auto auto;
            }

            .stage-card-scene,
            .stage-card-exits,
            .stage-card-npcs,
            .stage-card-items,
            .stage-card-story {
                grid-column: 1;
                grid-row: auto;
            }

            .stage-card-story {
                max-height: none;
            }
        }
        </style>
    """
    st.markdown(style_block.replace("__BG_ASPECT_RATIO__", background_aspect_ratio), unsafe_allow_html=True)


def render_header() -> None:
    state, player, scene, _, item_names, npc_names, exits = visible_scene_data()
    scene_name = scene.name if scene else "未进入场景"
    scene_desc = sanitize_display_text(scene.description.get_public_text() if scene else "游戏尚未初始化完成。")
    stage_dialogue = latest_stage_dialogue(scene_desc)
    dialogue_text = normalize_story_display_text(stage_dialogue.get("content") or scene_desc)
    is_security = stage_dialogue.get("kind") == "security"

    bg_uri = st.session_state.get("background_image_uri")
    fallback_text = "背景图未加载"
    if st.session_state.get("background_error"):
        fallback_text = sanitize_display_text(st.session_state.get("background_error"))
    elif st.session_state.get("background_status"):
        fallback_text = sanitize_display_text(st.session_state.get("background_status"))

    if exits:
        exits_markup = "".join(
            f"<span class='pill'>{html.escape(one['direction'])} · {html.escape(one['description'] or one['target_id'])}</span>"
            for one in exits
        )
    else:
        exits_markup = "<span class='pill'>当前没有可通往地点</span>"

    def pills(values: list[str], empty_text: str) -> str:
        if not values:
            return f"<span class='pill'>{html.escape(empty_text)}</span>"
        return "".join(f"<span class='pill'>{html.escape(v)}</span>" for v in values)

    render_html(
        f"""
        <div class="stage-shell">
            {f'<img class="stage-bg" src="{html.escape(bg_uri)}" alt="scene">' if bg_uri else f'<div class="stage-fallback">{html.escape(fallback_text)}</div>'}
            <div class="stage-mask"></div>
            <div class="stage-overlay">
                <section class="glass stage-card-scene">
                    <div class="eyeline">当前场景</div>
                    <h3>{html.escape(scene_name)}</h3>
                    <div class="scene-meta">回合 {state.turn_count} · 玩家 {html.escape(player.name if player else '未知')}</div>
                    <p class="scene-text">{format_text(scene_desc)}</p>
                </section>

                <section class="glass stage-card-exits">
                    <div class="eyeline">可通往地点</div>
                    <div class="pill-wrap">{exits_markup}</div>
                </section>

                <section class="glass stage-card-npcs">
                    <div class="eyeline">在场角色</div>
                    <div class="pill-wrap">{pills(npc_names, '当前没有其他在场角色')}</div>
                </section>

                <section class="glass stage-card-items">
                    <div class="eyeline">可见物品</div>
                    <div class="pill-wrap">{pills(item_names, '当前没有可见物品')}</div>
                </section>

                <section class="{'glass alert stage-card-story' if is_security else 'glass stage-card-story'}">
                    <div class="eyeline">{html.escape(str(stage_dialogue.get('speaker') or '剧情'))}</div>
                    <p class="scene-text">{format_text(dialogue_text)}</p>
                </section>
            </div>
        </div>
        """
    )


def render_main_scene_panel() -> None:
    """Reserved for compatibility; stage now contains scene blocks."""
    return


def render_feed_panel(*, show_title: bool = True, height: int = 360) -> None:
    if show_title:
        st.subheader("剧情记录")
    if not st.session_state.feed:
        st.caption("还没有回合记录。")
        return

    with st.container(height=height, border=True):
        for message in st.session_state.feed:
            with st.chat_message(message["role"]):
                kind = message.get("kind", "text")
                text = str(message.get("content", ""))
                if kind == "system":
                    st.caption(text)
                elif kind == "error":
                    st.error(text)
                elif kind == "security":
                    st.warning(text)
                    extra = message.get("extra", {})
                    if isinstance(extra, dict) and extra.get("hint"):
                        st.caption(str(extra["hint"]))
                elif kind == "check":
                    extra = message.get("extra", {})
                    st.info(
                        f"鉴定：{extra.get('result_text', '未知')} | d100={extra.get('dice_roll', '-')} | 目标={extra.get('target_value', '-')}"
                    )
                    if extra.get("detail"):
                        st.caption(str(extra["detail"]))
                elif kind == "ending":
                    st.warning(text)
                else:
                    st.markdown(f"<p>{format_text(text)}</p>", unsafe_allow_html=True)


def render_exit_buttons(exits: list[dict[str, str]], key_prefix: str) -> None:
    _ = key_prefix
    if not exits:
        st.caption("当前场景没有定义相邻出口。")
        return

    labels = [f"{one['direction']} → {one['description'] or one['target_id']}" for one in exits]
    render_chips(labels, "当前没有可通往地点。")


def render_quick_actions(key_prefix: str) -> None:
    screen_on = ai_screening_enabled()
    speed_fast = fast_speed_enabled()

    action_cols = st.columns(2, gap="small")
    left_label = f"筛查状态：{'开' if screen_on else '关'}"
    right_label = f"速度状态：{'极速' if speed_fast else '标准'}"

    if action_cols[0].button(left_label, key=f"{key_prefix}-screen-toggle", use_container_width=True):
        command = "\\screen ai off" if screen_on else "\\screen ai on"
        display = f"筛查状态切换为{'关' if screen_on else '开'}"
        handle_turn(command, display_input=display)
        st.rerun()

    if action_cols[1].button(right_label, key=f"{key_prefix}-speed-toggle", use_container_width=True):
        command = "\\speed quality" if speed_fast else "\\speed fast"
        display = f"速度状态切换为{'标准' if speed_fast else '极速'}"
        handle_turn(command, display_input=display)
        st.rerun()


def render_right_sidebar(show_title: bool = True, *, bordered: bool = True) -> None:
    state, player, scene, inventory_names, _item_names, _npc_names, exits = visible_scene_data()
    with st.container(border=bordered):
        if show_title:
            st.markdown("### 游戏信息")

        if not player:
            st.warning("当前未找到玩家角色。")
            return

        scene_name = scene.name if scene else "未知场景"
        st.caption(f"{scene_name} · 回合 {state.turn_count} · 背包 {len(inventory_names)} 项 · 可通往地点 {len(exits)}")

        with st.expander("背包", expanded=False):
            render_chips(inventory_names, "背包当前为空。")

        with st.expander("系统状态", expanded=True):
            runtime_status = get_runtime_control_status()
            render_fact_grid(
                [
                    ("AI筛查", runtime_status["ai_screening"]),
                    ("速度模式", runtime_status["speed_mode"]),
                ]
            )

        with st.expander("快捷命令", expanded=False):
            render_quick_actions("right-quick")


def render_story_log_toggle(*, floating: bool = False) -> None:
    _ = floating
    return


def render_game_info_toggle() -> None:
    return


def close_story_log() -> None:
    st.session_state.story_log_open = False


def close_game_info_dialog() -> None:
    st.session_state.right_sidebar_open = False


def render_story_log_dialog() -> None:
    render_feed_panel(show_title=True, height=420)


def render_game_info_dialog() -> None:
    render_right_sidebar(show_title=True, bordered=True)


def submit_action_input() -> None:
    prompt = str(st.session_state.get("action_input_value", "")).strip()
    if not prompt:
        return
    if st.session_state.get("turn_in_progress", False):
        return
    handle_turn(prompt)
    st.session_state.action_input_value = ""


def render_input_panel() -> None:
    engine = st.session_state.engine
    disabled = engine.is_game_over() or st.session_state.get("turn_in_progress", False)

    input_col, submit_col = st.columns([0.86, 0.14], gap="small", vertical_alignment="center")
    input_col.text_input(
        "输入你的行动",
        key="action_input_value",
        label_visibility="collapsed",
        placeholder="例如：我检查书桌抽屉",
        disabled=disabled,
        on_change=submit_action_input,
    )

    if submit_col.button(
        "发送",
        key="submit-action-input",
        use_container_width=True,
        type="primary",
        disabled=disabled,
    ):
        submit_action_input()
        st.rerun()


def render_dialogue_workspace() -> None:
    st.markdown("### 行动输入")
    render_input_panel()
    st.caption("可直接输入自然语言行动，例如：去东边看看、我去茅庐外。")

    with st.expander("剧情记录", expanded=False):
        st.markdown("<div class='feed-shell'>", unsafe_allow_html=True)
        render_feed_panel(show_title=False, height=380)
        st.markdown("</div>", unsafe_allow_html=True)


# 宸︿晶渚ц竟鏍忓彧淇濈暀蹇呰鎺у埗椤广€?
def render_sidebar() -> None:
    current_world = st.session_state.selected_world
    available_worlds = list_worlds()

    with st.sidebar:
        st.title(APP_TITLE)
        for one in startup_warnings():
            st.warning(one)

        selected_world = st.selectbox(
            "世界",
            options=available_worlds,
            index=available_worlds.index(current_world) if current_world in available_worlds else 0,
            format_func=world_label,
        )
        st.session_state.selected_world = selected_world

        st.markdown("---")
        available_saves = list_saves()
        current_save = st.session_state.get("_save_name", DEFAULT_SAVE)

        if available_saves:
            initial_save = current_save if current_save in available_saves else available_saves[0]
            save_name = st.selectbox(
                "存档",
                options=available_saves,
                index=available_saves.index(initial_save),
                key="selected_save_name",
            )
            st.session_state._save_name = save_name
        else:
            st.session_state._save_name = DEFAULT_SAVE
            st.caption("当前没有可读取的存档。首次保存后可在此选择。")

        action_col1, action_col2 = st.columns(2)
        if action_col1.button("开始新游戏", use_container_width=True, type="primary"):
            bootstrap_session(selected_world)
            st.rerun()
        if action_col2.button("读取存档", use_container_width=True, disabled=not bool(available_saves)):
            bootstrap_session(selected_world, load_name=st.session_state._save_name)
            st.rerun()

        if st.button("保存当前进度", use_container_width=True):
            engine = st.session_state.engine
            save_name = st.session_state.get("_save_name", DEFAULT_SAVE)
            ok = engine.save_game(save_name)
            if ok:
                st.success(f"已保存到 {save_name}")
            else:
                st.error(f"保存失败：{save_name}")

        st.markdown("---")
        st.checkbox("启用AI背景图", key="background_enabled", on_change=on_background_enabled_toggle)
        st.checkbox(
            "回合后自动更新背景图",
            key="background_auto_update",
            disabled=not bool(st.session_state.get("background_enabled", False)),
        )

        bg_col1, bg_col2 = st.columns(2)
        if bg_col1.button(
            "刷新背景",
            use_container_width=True,
            disabled=not bool(st.session_state.get("background_enabled", False)),
        ):
            seed = latest_stage_dialogue("").get("content", "")
            refresh_background_image(force=True, story_text=seed, ignore_enabled=False)
            st.rerun()
        if bg_col2.button("清除背景", use_container_width=True):
            clear_background_image()
            st.rerun()
        if not st.session_state.get("background_enabled", False):
            st.caption("AI 背景图已关闭，当前始终使用本地默认背景。")
        elif not st.session_state.get("background_auto_update", False):
            st.caption("已启用极速模式：背景图仅在你点击“刷新背景”时更新。")
        if st.session_state.get("background_status"):
            st.caption(str(st.session_state.get("background_status")))
        if st.session_state.get("background_error"):
            st.error(str(st.session_state.get("background_error")))

        st.markdown("---")
        with st.expander("系统状态与命令", expanded=False):
            render_right_sidebar(show_title=False, bordered=False)


def main() -> None:
    ensure_session()
    inject_styles(
        st.session_state.get("background_image_uri"),
        st.session_state.get("background_aspect_ratio", "3 / 2"),
    )
    render_sidebar()

    engine = st.session_state.engine
    render_header()
    render_dialogue_workspace()

    if engine.is_game_over():
        st.warning("游戏已经结束。你可以读取存档或重新开始新游戏。")

    # Dialog-style overlays are intentionally disabled in the simplified layout.


if __name__ == "__main__":
    main()
