# FILE: __init__.py
from __future__ import annotations

import configparser
import importlib.util
import os
import sys
import traceback
from typing import Any, Dict

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

if MODULE_DIR in sys.path:
    sys.path.remove(MODULE_DIR)
sys.path.insert(0, MODULE_DIR)

WEB_DIRECTORY = "./web/js"
CONFIG_PATH = os.path.join(MODULE_DIR, "config.ini")

_LOCAL_MODULE_NAMES = [
    "banana_logger",
    "banana_update",
    "banana_node",
    "banana_triple_view_node",
]

NODE_CLASS_MAPPINGS: Dict[str, Any] = {}
NODE_DISPLAY_NAME_MAPPINGS: Dict[str, str] = {}

CONFIG_DEFAULTS: Dict[str, str] = {
    "api_key": "",
    "base_url": "http://bj-aliyun-1.moki.wang:18000/api/",
    "fallback_base_url": "https://zheshihouduan.tenx-jingli.cloud/api",
    "manifest_url": "https://wen.tenx-jingli.cloud/plugins2/hrio_design_manifest.json",
    "model": "banano",
    "image_size": "2k",
    "aspect_ratio": "Auto",
    "verify_ssl": "false",
    "connect_timeout_sec": "30",
    "read_timeout_sec": "300",
    "timeout": "300",
    "request_timeout": "300",
    "max_retries": "3",
    "upload_dir": "shortlinks/qr",
    "enable_oss": "true",
    "force_hd": "true",
    "veo_poll_interval_sec": "8",
    "veo_poll_timeout_sec": "1800",
    "veo_resolution": "1080p",
    "veo_aspect_ratio": "16:9",
    "veo_duration_seconds": "8",
    "veo_number_of_videos": "1",
    "auto_update": "false",
    "check_interval_sec": "300",
    "force_update_on_startup": "false",
    "always_sync_files": "false",
}

PLUGIN_VERSION = "8.1.8"

PANEL_NODE_KEY = "Hrio_Design_Template_Node"
NORMAL_NODE_KEY = "Hrio_Design_Three_View_Node"
NORMAL_SINGLE_IMAGE_NODE_KEY = "Hrio_Design_Single_Image_Node"
NORMAL_SINGLE_VIDEO_NODE_KEY = "Hrio_Design_Single_Video_Node"
VIDEO_NODE_KEY = "Hrio_Design_Video_Node"

PANEL_NODE_DISPLAY = "🎨 Hrio Design｜设计师模板面板"
NORMAL_NODE_DISPLAY = "🎨 Hrio Design｜三方案并发"
NORMAL_SINGLE_IMAGE_NODE_DISPLAY = "🎨 Hrio Design｜单图生成"
NORMAL_SINGLE_VIDEO_NODE_DISPLAY = "🎨 Hrio Design｜单视频生成"
VIDEO_NODE_DISPLAY = "🎨 Hrio Design｜视频生成"

PANEL_NODE_CATEGORY = "HRIO设计/模板面板"
NORMAL_NODE_CATEGORY = "HRIO设计/普通"
VIDEO_NODE_CATEGORY = "HRIO设计/视频生成"


def _module_file(name: str) -> str:
    return os.path.join(MODULE_DIR, f"{name}.py")


def _is_local_module(module: Any) -> bool:
    path = getattr(module, "__file__", "") or ""
    if not path:
        return False

    try:
        path = os.path.abspath(path)
        return path.startswith(MODULE_DIR + os.sep)
    except Exception:
        return False


def _purge_foreign_modules() -> None:
    for name in _LOCAL_MODULE_NAMES:
        module = sys.modules.get(name)
        if module is None:
            continue

        if not _is_local_module(module):
            try:
                del sys.modules[name]
            except Exception:
                pass


def _load_local_module(name: str, force_reload: bool = False) -> Any:
    path = _module_file(name)

    if not os.path.exists(path):
        raise FileNotFoundError(f"缺少本地模块: {path}")

    old = sys.modules.get(name)
    if old is not None:
        if _is_local_module(old) and not force_reload:
            return old

        try:
            del sys.modules[name]
        except Exception:
            pass

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {name} -> {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sanitize_config() -> None:
    cfg = configparser.ConfigParser(strict=False)
    cfg.optionxform = str

    if os.path.exists(CONFIG_PATH):
        try:
            cfg.read(CONFIG_PATH, encoding="utf-8")
        except Exception:
            cfg = configparser.ConfigParser(strict=False)
            cfg.optionxform = str

    if not cfg.has_section("banana"):
        cfg.add_section("banana")

    for key, value in CONFIG_DEFAULTS.items():
        if not cfg.has_option("banana", key):
            cfg.set("banana", key, value)

    cfg.set("banana", "auto_update", "false")
    cfg.set("banana", "force_update_on_startup", "false")
    cfg.set("banana", "always_sync_files", "false")

    with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
        cfg.write(f)


def _make_node_class(base_cls: Any, new_name: str, category: str, extra_attrs: Dict[str, Any] | None = None) -> Any:
    attrs = {
        "CATEGORY": category,
        "__module__": getattr(base_cls, "__module__", "__main__"),
    }

    if extra_attrs:
        attrs.update(extra_attrs)

    return type(new_name, (base_cls,), attrs)


def _register_node(key: str, cls: Any, display: str, category: str) -> None:
    wrapped_cls = _make_node_class(
        cls,
        f"{key}_Class",
        category,
        {
            "__doc__": getattr(cls, "__doc__", None),
        },
    )

    NODE_CLASS_MAPPINGS[key] = wrapped_cls
    NODE_DISPLAY_NAME_MAPPINGS[key] = display


_purge_foreign_modules()
_sanitize_config()

try:
    logger_mod = _load_local_module("banana_logger", force_reload=True)
    logger = logger_mod.logger
except Exception:
    class _FallbackLogger:
        def info(self, m): print(f"[INFO] {m}", flush=True)
        def success(self, m): print(f"[OK] {m}", flush=True)
        def warning(self, m): print(f"[WARN] {m}", flush=True)
        def error(self, m): print(f"[ERR] {m}", flush=True)
        def summary(self, title, items):
            print(f"\n===== {title} =====", flush=True)
            for k, v in (items or {}).items():
                print(f"{k}: {v}", flush=True)
            print("", flush=True)

    logger = _FallbackLogger()


logger.info(f"🎨 Hrio Design 设计师模板加载器 v{PLUGIN_VERSION}")
logger.info(f"当前插件目录: {MODULE_DIR}")
logger.info(f"模板节点: {PANEL_NODE_KEY} => {PANEL_NODE_DISPLAY} | {PANEL_NODE_CATEGORY}")
logger.info(f"普通节点: {NORMAL_NODE_KEY} => {NORMAL_NODE_DISPLAY} | {NORMAL_NODE_CATEGORY}")
logger.info(f"普通单图节点: {NORMAL_SINGLE_IMAGE_NODE_KEY} => {NORMAL_SINGLE_IMAGE_NODE_DISPLAY} | {NORMAL_NODE_CATEGORY}")
logger.info(f"普通单输出视频节点: {NORMAL_SINGLE_VIDEO_NODE_KEY} => {NORMAL_SINGLE_VIDEO_NODE_DISPLAY} | {NORMAL_NODE_CATEGORY}")
logger.info(f"视频节点: {VIDEO_NODE_KEY} => {VIDEO_NODE_DISPLAY} | {VIDEO_NODE_CATEGORY}")
logger.info("已使用 Hrio_Design_* 独立节点 Key；可与旧 hrio-commerce / Banana 插件同时安装")
logger.info("Hrio Design 面板自动化只应用到 Hrio Design 独立节点，避免同步到旧 Banana 节点")

banana_node_mod = None

try:
    banana_node_mod = _load_local_module("banana_node", force_reload=True)

    required_names = [
        "_enum_source_options",
        "_enum_source_display",
        "_manual_model_default",
        "_manual_image_size_default",
        "_manual_aspect_ratio_default",
        "_upload_reference_images_for_node",
        "_run_three_view_jobs",
        "_runtime_results_payload",
        "_clear_runtime_results",
    ]

    missing = [name for name in required_names if not hasattr(banana_node_mod, name)]
    if missing:
        logger.warning("banana_node.py 可能不是新版，缺少: " + ", ".join(missing))
    else:
        logger.success("banana_node.py 已加载，三视图依赖函数完整")

except Exception as e:
    logger.error(f"banana_node.py 加载失败: {e}")
    logger.error(traceback.format_exc())


try:
    if banana_node_mod is not None:
        normal_three_cls = getattr(banana_node_mod, "HrioBananaNormalThreeViewConcurrentNodeV330", None)

        if normal_three_cls is not None:
            _register_node(
                NORMAL_NODE_KEY,
                normal_three_cls,
                NORMAL_NODE_DISPLAY,
                NORMAL_NODE_CATEGORY,
            )
            logger.success(f"Hrio Design 三方案并发节点已注册: {NORMAL_NODE_KEY}")
        else:
            normal_maps = getattr(banana_node_mod, "NODE_CLASS_MAPPINGS", {}) or {}

            loaded_normal_alias = 0
            for _old_key, old_cls in normal_maps.items():
                _register_node(
                    NORMAL_NODE_KEY,
                    old_cls,
                    NORMAL_NODE_DISPLAY,
                    NORMAL_NODE_CATEGORY,
                )
                loaded_normal_alias += 1
                break

            if loaded_normal_alias:
                logger.success(f"Hrio Design 三方案节点已注册: {NORMAL_NODE_KEY}")

        normal_single_image_cls = getattr(banana_node_mod, "HrioBananaNormalSingleImageNode", None)
        if normal_single_image_cls is not None:
            _register_node(
                NORMAL_SINGLE_IMAGE_NODE_KEY,
                normal_single_image_cls,
                NORMAL_SINGLE_IMAGE_NODE_DISPLAY,
                NORMAL_NODE_CATEGORY,
            )
            logger.success(f"普通单图节点已注册: {NORMAL_SINGLE_IMAGE_NODE_KEY}")
        else:
            logger.warning("banana_node.py 未找到 HrioBananaNormalSingleImageNode，跳过普通单图节点注册")

        normal_single_video_cls = getattr(banana_node_mod, "HrioBananaNormalVideoSingleOutputNode", None)
        if normal_single_video_cls is not None:
            _register_node(
                NORMAL_SINGLE_VIDEO_NODE_KEY,
                normal_single_video_cls,
                NORMAL_SINGLE_VIDEO_NODE_DISPLAY,
                NORMAL_NODE_CATEGORY,
            )
            logger.success(f"普通单输出视频节点已注册: {NORMAL_SINGLE_VIDEO_NODE_KEY}")
        else:
            logger.warning("banana_node.py 未找到 HrioBananaNormalVideoSingleOutputNode，跳过普通单输出视频节点注册")

except Exception as e:
    logger.error(f"Hrio Design 普通节点注册失败: {e}")
    logger.error(traceback.format_exc())


try:
    if banana_node_mod is not None:
        video_cls = getattr(banana_node_mod, "HrioBananaPromptVideoNode", None)
        if video_cls is not None:
            _register_node(
                VIDEO_NODE_KEY,
                video_cls,
                VIDEO_NODE_DISPLAY,
                VIDEO_NODE_CATEGORY,
            )
            logger.success(f"Hrio Design 生视频节点已注册: {VIDEO_NODE_KEY}")
        else:
            logger.warning("banana_node.py 未找到 HrioBananaPromptVideoNode，跳过生视频节点注册")
except Exception as e:
    logger.error(f"Hrio Design 生视频节点注册失败: {e}")
    logger.error(traceback.format_exc())


try:
    triple_mod = _load_local_module("banana_triple_view_node", force_reload=True)
    raw_maps = getattr(triple_mod, "NODE_CLASS_MAPPINGS", {}) or {}

    if not raw_maps and hasattr(triple_mod, "BananaPanelThreeViewNode"):
        raw_maps = {
            "BananaPanelThreeViewNode": getattr(triple_mod, "BananaPanelThreeViewNode")
        }

    loaded_panel = 0

    for _old_key, old_cls in raw_maps.items():
        _register_node(
            PANEL_NODE_KEY,
            old_cls,
            PANEL_NODE_DISPLAY,
            PANEL_NODE_CATEGORY,
        )
        loaded_panel += 1
        break

    logger.success(f"Hrio Design 设计师模板节点已注册: {PANEL_NODE_KEY}")

except Exception as e:
    logger.error(f"Hrio Design 模板面板节点加载失败: {e}")
    logger.error(traceback.format_exc())


logger.info(f"Hrio Design 插件最终加载 {len(NODE_CLASS_MAPPINGS)} 个节点:")
for key, display in NODE_DISPLAY_NAME_MAPPINGS.items():
    cls = NODE_CLASS_MAPPINGS.get(key)
    category = getattr(cls, "CATEGORY", "")
    logger.info(f"  · {key} => {display} | CATEGORY={category}")


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
