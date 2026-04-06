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

from src.main import initialize_game
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

WORLD_LABELS = {
    "mysterious_library": "COC",
    "daiyu_enters_jia": "林黛玉",
    "sanguo_mao_lu": "三顾茅庐",
}
ALLOWED_WORLDS = ["mysterious_library", "daiyu_enters_jia", "sanguo_mao_lu"]

_BACKGROUND_SERVICE: Any = None
_BACKGROUND_SERVICE_ERROR: str | None = None

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
    st.session_state.background_image_uri = None
    st.session_state.background_image_path = None
    st.session_state.background_prompt = ""
    st.session_state.background_source_signature = ""
    st.session_state.background_source_text = ""
    st.session_state.background_status = "等待生成首张背景图。"
    st.session_state.background_error = ""
    st.session_state.background_manual_clear = False
    st.session_state.background_aspect_ratio = "3 / 2"
    st.session_state.right_sidebar_open = False
    st.session_state.story_log_open = False
    st.session_state.turn_in_progress = False
    st.session_state.last_turn_input = ""
    st.session_state.last_turn_marker = None

    # Do not auto-generate background here; avoid blocking page bootstrap.


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
        st.session_state.background_enabled = True
    if "background_auto_update" not in st.session_state:
        # Default to off for smoother interactions on slower machines/networks.
        st.session_state.background_auto_update = False
    if "background_image_uri" not in st.session_state:
        st.session_state.background_image_uri = None
    if "background_image_path" not in st.session_state:
        st.session_state.background_image_path = None
    if "background_prompt" not in st.session_state:
        st.session_state.background_prompt = ""
    if "background_status" not in st.session_state:
        st.session_state.background_status = "等待生成首张背景图。"
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

    # Avoid auto-generating background during normal reruns.


def startup_warnings() -> list[str]:
    warnings: list[str] = []
    if _BACKGROUND_IMPORT_ERROR:
        warnings.append(f"背景图模块未成功加载，已自动降级。原因：{_BACKGROUND_IMPORT_ERROR}")
    if not DEFAULT_DB.exists():
        warnings.append(f"默认数据库不存在：{DEFAULT_DB}")
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


def summarize(text: str, limit: int = 90) -> str:
    normalized = " ".join((text or "").replace("\n", "，").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


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
        "world_name": st.session_state.get("selected_world", DEFAULT_WORLD),
    }


def refresh_background_image(force: bool = False, story_text: str = "") -> None:
    if not st.session_state.get("background_enabled", True):
        return

    service = get_background_service()
    if service is None:
        st.session_state.background_error = _BACKGROUND_SERVICE_ERROR or "当前未配置可用的图片生成服务。"
        st.session_state.background_status = "AI 背景图不可用，已保留默认背景。"
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
    st.session_state.background_status = (
        "背景图已从本地缓存恢复。" if generated.get("cache_hit") else "背景图已根据最新叙事更新。"
    )


def clear_background_image() -> None:
    st.session_state.background_image_uri = None
    st.session_state.background_image_path = None
    st.session_state.background_prompt = ""
    st.session_state.background_source_signature = ""
    st.session_state.background_source_text = ""
    st.session_state.background_manual_clear = True
    st.session_state.background_status = "已清除当前背景图，将回退到默认氛围底图。"
    st.session_state.background_error = ""


def add_feed(role: str, content: str, kind: str = "text", extra: dict[str, Any] | None = None) -> None:
    if not content:
        return
    safe_content = sanitize_display_text(content) if role == "assistant" else str(content)
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

    if st.session_state.get("turn_in_progress", False):
        return

    turn_marker = None
    try:
        turn_marker = getattr(engine.get_game_state(), "turn_count", None)
    except Exception:
        turn_marker = None

    if (
        text == st.session_state.get("last_turn_input", "")
        and turn_marker is not None
        and turn_marker == st.session_state.get("last_turn_marker")
    ):
        return

    st.session_state.turn_in_progress = True
    st.session_state.last_turn_input = text
    st.session_state.last_turn_marker = turn_marker

    add_feed("user", display_input or text)

    try:
        raw_result = engine.process_input(text)
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
        html, body, [class*="css"]  {
            font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
        }

        h1, h2, h3 {
            font-family: "STSong", "Noto Serif SC", serif !important;
            letter-spacing: 0.02em;
        }

        .stApp {
            background:
                linear-gradient(180deg, rgba(247, 241, 231, 0.96), rgba(240, 232, 220, 0.98)),
                radial-gradient(circle at top left, rgba(147, 95, 54, 0.10), transparent 28%),
                radial-gradient(circle at top right, rgba(65, 92, 79, 0.09), transparent 24%);
        }

        .main .block-container {
            max-width: 1520px;
            padding-top: 1.55rem;
            padding-bottom: 2.5rem;
            padding-left: 1rem;
            padding-right: 0.02rem;
        }

        .panel-card,
        .history-card,
        .input-card,
        .rail-card,
        .check-card {
            border: 1px solid rgba(69, 48, 34, 0.18);
            border-radius: 18px;
            padding: 1rem 1.15rem;
            background: rgba(255, 250, 244, 0.84);
            box-shadow: 0 18px 40px rgba(59, 39, 26, 0.08);
        }

        .stage-shell {
            position: relative;
            overflow: hidden;
            aspect-ratio: __BG_ASPECT_RATIO__;
            border-radius: 28px;
            border: 1px solid rgba(69, 48, 34, 0.22);
            box-shadow: 0 28px 60px rgba(50, 34, 23, 0.18);
            background: linear-gradient(135deg, rgba(60, 42, 29, 0.96), rgba(28, 20, 14, 0.96));
        }

        .stage-visual {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            background:
                radial-gradient(circle at top, rgba(255, 244, 224, 0.16), transparent 36%),
                linear-gradient(180deg, rgba(26, 19, 13, 0.1), rgba(18, 13, 9, 0.55));
        }

        .stage-visual img {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            display: block;
            object-fit: cover;
            object-position: center center;
            filter: saturate(1.03) contrast(1.02);
        }

        .stage-placeholder {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: 2.3rem;
            color: #f4e8da;
            background:
                radial-gradient(circle at top, rgba(255, 224, 187, 0.20), transparent 34%),
                linear-gradient(135deg, rgba(119, 78, 46, 0.92), rgba(45, 32, 22, 0.98));
        }

        .stage-scrim {
            position: absolute;
            inset: 0;
            background:
                linear-gradient(180deg, rgba(19, 13, 9, 0.18) 0%, rgba(19, 13, 9, 0.04) 32%, rgba(19, 13, 9, 0.58) 100%),
                linear-gradient(90deg, rgba(19, 13, 9, 0.22), rgba(19, 13, 9, 0) 42%, rgba(19, 13, 9, 0.14) 100%);
            pointer-events: none;
        }

        .stage-layer {
            position: absolute;
            inset: 1rem;
            z-index: 4;
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            align-content: start;
            overflow: auto;
        }

        .overlay-span {
            grid-column: 1 / -1;
        }

        .overlay-card {
            background: rgba(255, 248, 240, 0.72);
            border: 1px solid rgba(61, 45, 33, 0.24);
            border-radius: 14px;
            padding: 0.72rem 0.86rem;
            backdrop-filter: blur(5px);
            color: #2f241a;
            box-shadow: 0 8px 20px rgba(26, 18, 12, 0.12);
        }

        .overlay-security {
            border-color: rgba(176, 46, 46, 0.38);
            background: rgba(255, 238, 236, 0.8);
        }

        .overlay-title {
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            color: #6e4f39;
            margin-bottom: 0.35rem;
        }

        .overlay-card h3 {
            margin: 0 0 0.3rem;
            font-size: 1.14rem;
            color: #2a1f16;
        }

        .overlay-meta {
            font-size: 0.84rem;
            color: #4f3d2e;
            margin-bottom: 0.36rem;
        }

        .overlay-card p {
            margin: 0;
            line-height: 1.55;
            color: #2b221a;
        }

        .overlay-list {
            margin: 0;
            padding-left: 1rem;
            line-height: 1.52;
        }

        .overlay-note {
            margin-top: 0.4rem;
            font-size: 0.84rem;
            color: #5d4736;
        }

        .overlay-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
        }

        .overlay-chip,
        .overlay-empty {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.22rem 0.56rem;
            font-size: 0.84rem;
            border: 1px solid rgba(95, 73, 54, 0.3);
            background: rgba(255, 255, 255, 0.6);
            color: #3b2e23;
        }

        .stage-topbar,
        .stage-dialogue {
            position: absolute;
            left: 1.2rem;
            right: 1.2rem;
            z-index: 2;
        }

        .stage-topbar {
            top: 1.15rem;
            display: flex;
            justify-content: flex-start;
            align-items: flex-start;
        }

        .scene-overlay {
            position: relative;
            max-width: min(22rem, calc(100% - 8rem));
            border-radius: 18px;
            background: rgba(35, 25, 18, 0.42);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 239, 226, 0.12);
            overflow: hidden;
        }

        .scene-overlay summary,
        .stage-dialogue-details summary {
            list-style: none;
            cursor: pointer;
        }

        .scene-overlay summary {
            padding: 0.62rem 0.82rem;
            color: #fff6ee;
            font-size: 0.84rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .scene-overlay[open] summary {
            position: absolute;
            inset: 0;
            z-index: 3;
            padding: 0;
            background: transparent;
        }

        .scene-overlay[open] summary span {
            opacity: 0;
        }

        .scene-overlay summary::-webkit-details-marker,
        .stage-dialogue-details summary::-webkit-details-marker {
            display: none;
        }

        .scene-overlay-body {
            padding: 0 0.82rem 0.88rem;
            border-top: 1px solid rgba(255, 239, 226, 0.10);
        }

        .scene-overlay-title {
            display: none;
        }

        .scene-overlay-body h3 {
            margin: 0.72rem 0 0.35rem;
            color: #fff7ef;
            font-size: 1.08rem;
        }

        .scene-overlay-body p {
            margin: 0;
            color: rgba(255, 244, 235, 0.92);
            font-size: 0.94rem;
            line-height: 1.66;
        }

        .scene-overlay:not([open]) .scene-overlay-body,
        .stage-dialogue-details:not([open]) .stage-dialogue-body {
            display: none;
        }

        .scene-overlay[open] .scene-overlay-body {
            position: relative;
            z-index: 2;
            padding-top: 0.82rem;
            padding-bottom: 1rem;
            pointer-events: none;
        }

        .scene-overlay[open] .scene-overlay-title {
            display: block;
            margin: 0 0 0.45rem;
            color: #fff3e4;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .stage-hud {
            position: absolute;
            right: 1.2rem;
            top: 1.15rem;
            z-index: 2;
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 0.5rem;
            max-width: 42%;
        }

        .stage-hud span {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.34rem 0.74rem;
            background: rgba(34, 25, 18, 0.54);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 238, 221, 0.16);
            color: #fff6ee;
            font-size: 0.84rem;
            white-space: nowrap;
        }

        .eyebrow {
            text-transform: uppercase;
            letter-spacing: 0.16em;
            font-size: 0.72rem;
            color: #6f5846;
            margin-bottom: 0.45rem;
            font-weight: 600;
        }

        .scene-overlay .eyebrow,
        .stage-placeholder .eyebrow,
        .stage-dialogue .eyebrow {
            color: rgba(255, 236, 219, 0.76);
        }

        .stage-dialogue-bottom {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 1.2rem 1.5rem 1.5rem;
            background: linear-gradient(to top, rgba(15, 10, 6, 0.92) 0%, rgba(15, 10, 6, 0.75) 60%, transparent 100%);
            border-radius: 0 0 28px 28px;
            z-index: 3;
        }

        .stage-dialogue-bottom .eyebrow {
            color: rgba(255, 236, 219, 0.85);
            margin-bottom: 0.4rem;
            font-size: 0.75rem;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .stage-dialogue-bottom p {
            margin: 0;
            color: rgba(255, 248, 240, 0.95);
            font-size: 1rem;
            line-height: 1.65;
            max-height: 6rem;
            overflow-y: auto;
        }

        .dialogue-shell {
            padding: 1rem 1.05rem;
        }

        .dialogue-shell p {
            margin: 0.2rem 0 0;
            color: #59473a;
        }

        .story-log-button {
            display: flex;
            align-items: center;
            min-height: 100%;
        }

        .story-log-button.story-log-floating {
            position: fixed;
            top: 1.92rem;
            right: 10.1rem;
            z-index: 1200;
            width: auto;
        }

        .story-log-button.story-log-floating .stButton {
            width: auto;
            margin: 0;
        }

        .story-log-button.story-log-floating .stButton > button {
            min-height: 3rem;
            width: auto;
            height: 3rem;
            padding: 0.3rem 0.72rem;
            border-radius: 0.78rem;
            border: 1px solid rgba(103, 79, 60, 0.24);
            background: rgba(255, 250, 244, 0.96);
            box-shadow: 0 10px 22px rgba(61, 43, 30, 0.08);
            backdrop-filter: blur(10px);
            color: #4a3629;
        }

        .gear-toggle {
            display: flex;
            justify-content: flex-end;
            align-items: flex-start;
            width: auto;
        }

        .gear-toggle .stButton {
            width: auto;
            margin: 0;
        }

        .gear-toggle .stButton > button {
            min-height: 3rem;
            width: auto;
            height: 3rem;
            padding: 0.45rem 0.95rem;
            border-radius: 0.82rem;
            border: 1px solid rgba(103, 79, 60, 0.24);
            background: rgba(255, 250, 244, 0.96);
            box-shadow: 0 10px 22px rgba(61, 43, 30, 0.12);
            color: #4a3629;
            font-size: 0.92rem !important;
            font-weight: 700;
            letter-spacing: 0.02em;
            line-height: 1 !important;
            white-space: nowrap;
        }

        .story-log-button .stButton {
            width: 100%;
            margin: 0;
        }

        .story-log-button .stButton > button {
            min-height: 3rem;
            height: 3rem;
            border-radius: 0.78rem;
            border: 1px solid rgba(103, 79, 60, 0.24);
            background: rgba(255, 250, 244, 0.96);
            box-shadow: 0 10px 22px rgba(61, 43, 30, 0.08);
            padding: 0.3rem 0.72rem;
        }

        div[data-testid="stHorizontalBlock"]:has(.story-log-button) {
            margin-top: -0.68rem;
            align-items: center;
        }

        div[data-testid="stHorizontalBlock"]:has(.story-log-button) > div[data-testid="column"] {
            display: flex;
            align-items: center;
        }

        div[data-testid="stHorizontalBlock"]:has(.right-rail-title) {
            align-items: flex-start;
        }

        div[data-testid="stHorizontalBlock"]:has(.right-rail-title) > div[data-testid="column"]:first-child {
            margin-top: -0.68rem;
        }

        .right-rail-title {
            padding: 0.9rem 1rem;
            margin-bottom: 0.85rem;
            border-radius: 18px;
            border: 1px solid rgba(112, 84, 62, 0.24);
            background: linear-gradient(180deg, rgba(221, 206, 188, 0.97), rgba(209, 191, 171, 0.98));
            box-shadow: 0 18px 34px rgba(58, 40, 28, 0.10);
        }

        .right-rail-title h3 {
            margin: 0;
            color: #2f241c;
            font-size: 1.34rem;
            font-weight: 800;
            text-align: center;
        }

        .info-overview {
            margin-bottom: 0.9rem;
            padding: 0.95rem 1rem;
            border-radius: 18px;
            border: 1px solid rgba(118, 89, 66, 0.16);
            background: linear-gradient(180deg, rgba(246, 239, 230, 0.98), rgba(237, 228, 214, 0.98));
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
        }

        .info-overview h4 {
            margin: 0.1rem 0 0.4rem;
            color: #2d221b;
            font-size: 1.18rem;
            font-weight: 700;
        }

        .info-overview p {
            margin: 0;
            color: #5b4739;
            font-size: 0.94rem;
            line-height: 1.58;
        }

        .section-note {
            margin: 0 0 0.75rem;
            color: #6a5546;
            font-size: 0.85rem;
            line-height: 1.45;
        }

        .status-metrics-wrap {
            display: flex;
            justify-content: center;
            padding: 0.78rem 0 1.68rem;
        }

        .status-metrics {
            display: flex;
            flex-direction: column;
            gap: 0.22rem;
            width: min(100%, 14rem);
            margin: 0 auto;
        }

        .status-card {
            border: none;
            background: transparent;
            padding: 0.14rem 0;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            min-height: auto;
            text-align: left;
            width: 100%;
            line-height: 1.45;
        }

        .status-card-label {
            display: inline-flex;
            color: #2b211a;
            font-size: 1rem;
            letter-spacing: 0;
            text-transform: none;
            white-space: nowrap;
            font-weight: 400;
            line-height: 1.45;
        }

        .status-card-value {
            display: inline-grid;
            grid-template-columns: 4ch 1ch 4ch;
            align-items: center;
            justify-content: end;
            color: #2b211a;
            font-size: 1rem;
            line-height: 1.45;
            font-weight: 400;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }

        .status-card-current,
        .status-card-max {
            display: inline-block;
        }

        .status-card-current {
            text-align: right;
        }

        .status-card-sep {
            text-align: center;
        }

        .status-card-max {
            text-align: left;
        }

        .artifact-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
        }

        .artifact-chip {
            display: inline-flex;
            align-items: center;
            padding: 0.34rem 0.78rem;
            border-radius: 999px;
            border: 1px solid rgba(101, 76, 57, 0.18);
            background: linear-gradient(180deg, rgba(241, 231, 215, 0.96), rgba(231, 219, 201, 0.96));
            color: #47352b;
            font-size: 0.9rem;
            box-shadow: 0 8px 16px rgba(73, 52, 37, 0.05);
        }

        .fact-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.72rem;
        }

        .fact-card {
            padding: 0.72rem 0.82rem;
            border-radius: 14px;
            border: 1px solid rgba(112, 84, 62, 0.16);
            background: rgba(255, 250, 244, 0.78);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
        }

        .fact-label {
            display: block;
            margin-bottom: 0.16rem;
            color: #705748;
            font-size: 0.74rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .fact-value {
            display: block;
            color: #2d221b;
            font-size: 1.02rem;
            font-weight: 700;
        }

        .check-card strong {
            font-size: 1.05rem;
        }

        .check-card {
            border-radius: 14px;
            padding: 0.92rem 1rem;
            background: rgba(255, 250, 244, 0.82);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.56);
        }

        .check-card.critical { border-left: 6px solid #315b4c; }
        .check-card.success { border-left: 6px solid #55734a; }
        .check-card.failure { border-left: 6px solid #9a6d34; }
        .check-card.fumble { border-left: 6px solid #7b2f2f; }

        .stButton > button {
            border-radius: 999px;
            border: 1px solid rgba(94, 68, 50, 0.2);
            min-height: 2.45rem;
            background: rgba(255, 249, 241, 0.88);
            color: #2b211a;
            font-weight: 600;
        }

        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #8a5a34, #6e4424);
            color: #fffaf2;
            border-color: #6e4424;
        }

        .story-log-button .stButton > button,
        .sidebar-toggle .stButton > button {
            font-size: 0.92rem;
        }

        .story-log-button .stButton > button p {
            white-space: nowrap;
            line-height: 1;
            text-align: center;
        }

        div[data-testid="stHorizontalBlock"]:has(.story-log-button) > div[data-testid="column"]:first-child button {
            font-size: 0.5rem !important;
        }

        div[data-testid="stHorizontalBlock"]:has(.story-log-button) > div[data-testid="column"]:first-child button * {
            font-size: 0.5rem !important;
            line-height: 1 !important;
            white-space: nowrap !important;
        }

        div[data-testid="stChatMessage"] {
            background: rgba(255, 250, 245, 0.7);
            border: 1px solid rgba(94, 68, 50, 0.11);
            border-radius: 18px;
            padding: 0.3rem 0.5rem;
        }

        div[data-testid="stExpander"] {
            border: 1px solid rgba(108, 80, 58, 0.18);
            border-radius: 16px;
            background: linear-gradient(180deg, rgba(233, 220, 204, 0.95), rgba(223, 208, 191, 0.97));
            box-shadow: 0 12px 24px rgba(60, 42, 30, 0.07);
        }

        div[data-testid="stExpander"] summary {
            padding: 0.18rem 0.08rem;
            color: #2d221b;
            font-weight: 700;
            font-size: 1rem;
            letter-spacing: 0.01em;
        }

        div[data-testid="stExpanderDetails"] {
            padding-top: 0.96rem;
            padding-bottom: 1.18rem;
        }

        @media (max-width: 980px) {
            .main .block-container {
                padding-top: 1.1rem;
            }

            .stage-shell,
            .stage-visual {
                aspect-ratio: auto;
            }

            .stage-topbar {
                flex-direction: column;
            }

            .scene-overlay,
            .stage-hud {
                max-width: 100%;
            }

            .stage-dialogue {
                left: 1rem;
                right: 1rem;
                max-width: none;
                bottom: 1rem;
            }

            .story-log-button.story-log-floating {
                top: 1rem;
                right: 8.9rem;
            }

            .stage-layer {
                grid-template-columns: 1fr;
                inset: 0.7rem;
            }

            .overlay-span {
                grid-column: auto;
            }
        }
        </style>
        """
    st.markdown(style_block.replace("__BG_ASPECT_RATIO__", background_aspect_ratio), unsafe_allow_html=True)


# 涓昏瑙夎垶鍙帮細淇濈暀鑳屾櫙鍥俱€佸満鏅弿杩版偓娴崱鍜岃交閲忎俊鎭?HUD銆?
def render_header() -> None:
    state, player, scene, _, item_names, npc_names, exits = visible_scene_data()
    scene_name = scene.name if scene else "未进入场景"
    raw_description = scene.description.get_public_text() if scene else "游戏尚未初始化完成。"
    description = sanitize_display_text(raw_description)
    stage_dialogue = latest_stage_dialogue(description)
    dialogue_content = sanitize_display_text(stage_dialogue.get("content") or description or "调查仍在继续。")
    is_security_dialogue = stage_dialogue.get("kind") == "security"

    background_image_uri = (
        st.session_state.get("background_image_uri")
        if st.session_state.get("background_enabled", True)
        else None
    )
    visual_markup = (
        f'<img src="{html.escape(background_image_uri)}" alt="{html.escape(scene_name)}">'
        if background_image_uri
        else f"""
        <div class="stage-placeholder">
            <div class="eyebrow">Visual Stage</div>
            <h2>{html.escape(scene_name)}</h2>
            <p>{format_text(description)}</p>
        </div>
        """
    )

    def _chip_markup(values: list[str], empty_text: str) -> str:
        if not values:
            return f'<span class="overlay-empty">{html.escape(empty_text)}</span>'
        return "".join(f'<span class="overlay-chip">{html.escape(one)}</span>' for one in values)

    if exits:
        exits_markup = "".join(
            f"<li>{html.escape(one['direction'])} · {html.escape(one['description'] or one['target_id'])}</li>"
            for one in exits
        )
        exits_markup = f'<ul class="overlay-list">{exits_markup}</ul>'
    else:
        exits_markup = '<span class="overlay-empty">当前没有可通往地点。</span>'

    scene_meta = f"回合 {state.turn_count} · 玩家 {player.name if player else '未知'}"
    dialogue_card_class = "overlay-card overlay-span overlay-security" if is_security_dialogue else "overlay-card overlay-span"

    render_html(
        f"""
        <div class="stage-shell">
            <div class="stage-visual">
                {visual_markup}
                <div class="stage-scrim"></div>
            </div>
            <div class="stage-layer">
                <section class="overlay-card overlay-span">
                    <div class="overlay-title">当前场景</div>
                    <h3>{html.escape(scene_name)}</h3>
                    <div class="overlay-meta">{html.escape(scene_meta)}</div>
                    <p>{format_text(description)}</p>
                </section>

                <section class="overlay-card overlay-span">
                    <div class="overlay-title">可通往地点</div>
                    {exits_markup}
                    <div class="overlay-note">移动请在输入框手动输入：\\move 方向</div>
                </section>

                <section class="overlay-card">
                    <div class="overlay-title">在场角色</div>
                    <div class="overlay-chips">{_chip_markup(npc_names, "当前没有其他在场角色。")}</div>
                </section>

                <section class="overlay-card">
                    <div class="overlay-title">可见物品</div>
                    <div class="overlay-chips">{_chip_markup(item_names, "当前没有可见物品。")}</div>
                </section>

                <section class="{dialogue_card_class}">
                    <div class="overlay-title">{html.escape(str(stage_dialogue.get("speaker") or "剧情"))}</div>
                    <p>{format_text(dialogue_content)}</p>
                </section>
            </div>
        </div>
        """
    )


def render_main_scene_panel() -> None:
    """Reserved for compatibility; scene summary is now rendered in the stage overlay."""
    return

def render_feed_panel(*, show_title: bool = True, height: int = 420) -> None:
    if show_title:
        st.subheader("剧情记录")
    if not st.session_state.feed:
        st.caption("还没有回合记录。")
        return

    with st.container(height=height, border=True):
        for message in st.session_state.feed:
            with st.chat_message(message["role"]):
                kind = message.get("kind", "text")
                if kind == "check":
                    extra = message.get("extra", {})
                    render_html(
                        f"""
                        <div class="check-card {html.escape(extra.get('result_class', 'neutral'))}">
                            <div class="eyebrow">Check Result</div>
                            <strong>{html.escape(extra.get('result_text', '未知'))}</strong><br>
                            d100：{extra.get('dice_roll', '-')} / 目标值：{extra.get('target_value', '-')} / 属性值：{extra.get('actor_value', '-')}
                        </div>
                        """
                    )
                    if extra.get("detail"):
                        st.caption(extra["detail"])
                elif kind == "system":
                    st.caption(message["content"])
                elif kind == "error":
                    st.error(message["content"])
                elif kind == "security":
                    st.warning(message["content"])
                    extra = message.get("extra", {})
                    if isinstance(extra, dict) and extra.get("hint"):
                        st.caption(str(extra["hint"]))
                elif kind == "ending":
                    st.warning(message["content"])
                else:
                    st.markdown(
                        f"<p>{format_text(str(message.get('content', '')))}</p>",
                        unsafe_allow_html=True,
                    )


def render_exit_buttons(exits: list[dict[str, str]], key_prefix: str) -> None:
    _ = key_prefix
    if not exits:
        st.caption("当前场景没有定义相邻出口。")
        return

    labels = [f"{one['direction']} → {one['description'] or one['target_id']}" for one in exits]
    render_chips(labels, "当前没有可通往地点。")
    st.caption("移动请在输入框手动输入：\\move 方向")


def render_quick_actions(key_prefix: str) -> None:
    action_cols = st.columns(2, gap="small")
    quick_actions = [
        ("筛查状态", "\\screen ai status"),
        ("筛查开启", "\\screen ai on"),
        ("筛查关闭", "\\screen ai off"),
        ("速度状态", "\\speed status"),
        ("极速模式", "\\speed fast"),
        ("质量模式", "\\speed quality"),
    ]
    for idx, (label, command) in enumerate(quick_actions):
        target = action_cols[idx % 2]
        if target.button(label, key=f"{key_prefix}-{idx}", use_container_width=True):
            handle_turn(command, display_input=label)
            st.rerun()


def render_right_sidebar(show_title: bool = True, *, bordered: bool = True) -> None:
    state, player, scene, inventory_names, _item_names, _npc_names, exits = visible_scene_data()
    with st.container(border=bordered):
        if show_title:
            render_html(
                """
                <div class="right-rail-title">
                    <h3>游戏信息</h3>
                </div>
                """
            )

        if not player:
            st.warning("当前未找到玩家角色。")
            return

        scene_name = scene.name if scene else "未知场景"
        scene_summary = " · ".join(
            [
                f"回合 {state.turn_count}",
                f"背包 {len(inventory_names)} 项",
                f"可通往地点 {len(exits)}",
            ]
        )
        render_html(
            f"""
            <div class="info-overview">
                <div class="eyebrow">当前概览</div>
                <h4>{html.escape(scene_name)}</h4>
                <p>{html.escape(scene_summary)}</p>
            </div>
            """
        )

        with st.expander("背包", expanded=False):
            render_chips(inventory_names, "背包当前为空。")

        with st.expander("移动路线", expanded=False):
            render_exit_buttons(exits, key_prefix="right-move")

        with st.expander("常用动作", expanded=False):
            runtime_status = get_runtime_control_status()
            render_fact_grid(
                [
                    ("AI筛查", runtime_status["ai_screening"]),
                    ("速度模式", runtime_status["speed_mode"]),
                ]
            )
            render_quick_actions("right-quick")


def render_story_log_toggle(*, floating: bool = False) -> None:
    class_name = "story-log-button story-log-floating" if floating else "story-log-button"
    st.markdown(f'<div class="{class_name}">', unsafe_allow_html=True)
    if st.button("鍓ф儏", key="story-log-toggle", use_container_width=True):
        st.session_state.story_log_open = True
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# 娓告垙淇℃伅鍏ュ彛鏀惧湪宸︿晶杈规爮閲岋紝鐐瑰嚮鍚庡脊鍑烘父鎴忎俊鎭獥鍙ｃ€?
def render_game_info_toggle() -> None:
    if st.button("娓告垙淇℃伅", key="game-info-toggle", use_container_width=True):
        st.session_state.right_sidebar_open = True
        st.rerun()


# 鍓ф儏璁板綍鍏抽棴鍥炶皟銆?
def close_story_log() -> None:
    st.session_state.story_log_open = False


# 娓告垙淇℃伅鍏抽棴鍥炶皟銆?
def close_game_info_dialog() -> None:
    st.session_state.right_sidebar_open = False


# 鍓ф儏璁板綍浠ュぇ寮瑰眰褰㈠紡灞曠ず锛岄伩鍏嶅帇缂╀富杈撳叆鍖恒€?
@st.dialog("鍓ф儏璁板綍", width="large", on_dismiss=close_story_log)
def render_story_log_dialog() -> None:
    render_feed_panel(show_title=False, height=560)
    if st.button("鍏抽棴鍓ф儏璁板綍", key="close-story-log-dialog", use_container_width=True):
        close_story_log()
        st.rerun()


# 娓告垙淇℃伅鐢ㄤ笌鈥滃墽鎯呪€濅竴鑷寸殑寮瑰眰灞曞紑銆?
@st.dialog("娓告垙淇℃伅", width="large", on_dismiss=close_game_info_dialog)
def render_game_info_dialog() -> None:
    render_right_sidebar(show_title=False, bordered=False)
    if st.button("鍏抽棴娓告垙淇℃伅", key="close-game-info-dialog", use_container_width=True):
        close_game_info_dialog()
        st.rerun()


# 杈撳叆妗嗘彁浜ゅ洖璋冿細鏀寔鍥炶溅鍜屽彂閫佹寜閽叡鐢ㄥ悓涓€濂楅€昏緫銆?
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
    weights = [1.0, 4.55] if st.session_state.story_log_open else [0.74, 4.78]
    log_col, input_col = st.columns(weights, gap="small", vertical_alignment="center")

    with log_col:
        render_story_log_toggle()

    with input_col:
        render_input_panel()


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
        st.checkbox("启用AI背景图", key="background_enabled")
        st.checkbox("回合后自动更新背景图", key="background_auto_update")

        bg_col1, bg_col2 = st.columns(2)
        if bg_col1.button("刷新背景", use_container_width=True):
            seed = latest_stage_dialogue("").get("content", "")
            refresh_background_image(force=True, story_text=seed)
            st.rerun()
        if bg_col2.button("清除背景", use_container_width=True):
            clear_background_image()
            st.rerun()
        if not st.session_state.get("background_auto_update", False):
            st.caption("已启用极速模式：背景图仅在你点击“刷新背景”时更新。")

        st.markdown("---")
        render_game_info_toggle()


def main() -> None:
    ensure_session()
    inject_styles(
        (
            st.session_state.get("background_image_uri")
            if st.session_state.get("background_enabled", True)
            else None
        ),
        st.session_state.get("background_aspect_ratio", "3 / 2"),
    )
    render_sidebar()

    engine = st.session_state.engine
    render_header()
    render_main_scene_panel()
    render_dialogue_workspace()

    if engine.is_game_over():
        st.warning("游戏已经结束。你可以读取存档或重新开始新游戏。")

    if st.session_state.story_log_open:
        render_story_log_dialog()
    if st.session_state.right_sidebar_open:
        render_game_info_dialog()


if __name__ == "__main__":
    main()

























