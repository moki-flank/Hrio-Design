# FILE: banana_update.py
from __future__ import annotations

import configparser
import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, Tuple

import requests

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(MODULE_DIR, "config.ini")
LOCAL_MANIFEST_PATH = os.path.join(MODULE_DIR, "banana_manifest.json")
STATE_PATH = os.path.join(MODULE_DIR, "banana_state.json")
BACKUP_DIR = os.path.join(MODULE_DIR, ".banana_backups")

DEFAULT_MANIFEST_URL = "https://wen.tenx-jingli.cloud/plugins2/hrio_design_manifest.json"
DEFAULT_REMOTE_API_BASE_URL = "https://zheshihouduan.tenx-jingli.cloud/api/"

LEGACY_API_BASE_URLS = {
    "https://zheshihouduan.tenx-jingli.cloud/api",
    "https://zheshihouduan.tenx-jingli.cloud/api/",
}

DEFAULT_MANIFEST: Dict[str, Any] = {
    "plugin_version": "8.1.4",
    "schema_version": 1,
    "config_defaults": {
        "base_url": DEFAULT_REMOTE_API_BASE_URL,
        "manifest_url": DEFAULT_MANIFEST_URL,
        "model": "banano",
        "image_size": "2k",
        "aspect_ratio": "Auto",
        "verify_ssl": "false",
        "connect_timeout_sec": "30",
        "read_timeout_sec": "300",
        "upload_dir": "shortlinks/qr",
        "enable_oss": "true",
        "force_hd": "true",
        "veo_poll_interval_sec": "8",
        "veo_poll_timeout_sec": "1800",
        "veo_resolution": "1080p",
        "veo_aspect_ratio": "16:9",
        "veo_duration_seconds": "8",
        "veo_number_of_videos": "1",
    },
    "node": {
        "display_name": "🎨 Hrio Design 独立图像/视频生成",
        "category": "HRIO设计/Image",
        "output_node": True,
        "model_map": {
            "banano2": "banano",
            "banano-pro": "banano-pro",
            "veo3.1": "veo3.1",
            "gemini3.1-pro": "gemini3.1-pro",
        },
        "enum_sources": {
            "model_map": {
                "banano2": "banano",
                "banano-pro": "banano-pro",
                "veo3.1": "veo3.1",
                "gemini3.1-pro": "gemini3.1-pro",
            },
            "aspect_ratio_options": {
                "Auto": "Auto",
                "Auto (自动)": "Auto",
                "1:1 (方形)": "1:1",
                "1:4 (超高竖图)": "1:4",
                "1:8 (极高竖图)": "1:8",
                "2:3 (竖屏摄影)": "2:3",
                "3:2 (横屏摄影)": "3:2",
                "3:4 (竖屏标准)": "3:4",
                "4:1 (超宽横幅)": "4:1",
                "4:3 (横屏标准)": "4:3",
                "4:5 (竖版海报)": "4:5",
                "5:4 (近方横图)": "5:4",
                "8:1 (极宽横幅)": "8:1",
                "9:16 (竖屏/手机)": "9:16",
                "16:9 (横屏宽幅)": "16:9",
                "21:9 (电影宽屏)": "21:9",
            },
            "image_size_options": {
                "1K": "1K",
                "2K": "2K",
                "4K": "4K",
                "8K（默认16:9）": "8K",
            },
            "veo_resolution_options": {
                "1080p": "1080p",
                "720p": "720p",
            },
            "video_resolution_options": {
                "1080p": "1080p",
                "720p": "720p",
            },
            "video_aspect_ratio_options": {
                "16:9 (横屏宽幅)": "16:9",
                "9:16 (竖屏/手机)": "9:16",
            },
        },
        "required_fields": [],
        "extra_optional_fields": [],
        "optional_image_slots": 10,
    },
    "files": {
        "banana_manifest.json": {"url": DEFAULT_MANIFEST_URL},
        "banana_update.py": {"url": "https://wen.tenx-jingli.cloud/plugins2/banana_update.py"},
        "banana_node.py": {"url": "https://wen.tenx-jingli.cloud/plugins2/banana_node.py"},
        "banana_triple_view_node.py": {"url": "https://wen.tenx-jingli.cloud/plugins2/banana_triple_view_node.py"},
        "banana_logger.py": {"url": "https://wen.tenx-jingli.cloud/plugins2/banana_logger.py"},
        "__init__.py": {"url": "https://wen.tenx-jingli.cloud/plugins2/__init__.py"},
        "banana_ecommerce_prompts.json": {"url": "https://wen.tenx-jingli.cloud/plugins2/banana_ecommerce_prompts.json"},
        "web/banana_prompt_editor.html": {"url": "https://wen.tenx-jingli.cloud/plugins2/web/banana_prompt_editor.html"},
        "web/js/banana_triple_view_ui.js": {"url": "https://wen.tenx-jingli.cloud/plugins2/web/js/banana_triple_view_ui.js"},
        "web/js/banana_player.js": {"url": "https://wen.tenx-jingli.cloud/plugins2/web/js/banana_player.js"},
    },
}


def _log(level: str, msg: str) -> None:
    print(f"[HrioDesignUpdate][{level}] {msg}", flush=True)


def _deep_copy(obj: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(obj, ensure_ascii=False))


def _read_json(path: str, default: Dict[str, Any]) -> Dict[str, Any]:
    if not os.path.exists(path):
        return _deep_copy(default)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            merged = _deep_copy(default)
            _deep_merge_inplace(merged, data)
            return merged

        return _deep_copy(default)
    except Exception as e:
        _log("WARN", f"读取 JSON 失败，使用默认值: {path} | {e}")
        return _deep_copy(default)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, path)


def _deep_merge_inplace(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge_inplace(base[key], value)
        else:
            base[key] = value
    return base


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_version(ver: Any) -> Tuple[int, ...]:
    raw = str(ver or "").strip()
    if not raw:
        return (0,)

    parts = []
    for part in raw.replace("-", ".").replace("_", ".").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)

    return tuple(parts) if parts else (0,)


def _cfg_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _cfg_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def load_state() -> Dict[str, Any]:
    return _read_json(STATE_PATH, {
        "last_check_ts": 0,
        "plugin_version": "0.0.0",
        "schema_version": 0,
        "last_manifest_url": "",
        "last_remote_plugin_version": "",
        "last_remote_schema_version": 0,
        "last_update_status": "",
        "last_error": "",
        "files": {},
    })


def save_state(state: Dict[str, Any]) -> None:
    _write_json(STATE_PATH, state)


def load_local_manifest() -> Dict[str, Any]:
    return _read_json(LOCAL_MANIFEST_PATH, DEFAULT_MANIFEST)


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        cfg.read(CONFIG_PATH, encoding="utf-8")

    if not cfg.has_section("banana"):
        cfg["banana"] = {}

    return cfg


def save_config(cfg: configparser.ConfigParser) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)


def migrate_config_ini() -> None:
    cfg = load_config()
    sec = cfg["banana"]

    changed = False

    defaults = {
        "api_key": "",
        "base_url": DEFAULT_REMOTE_API_BASE_URL,
        "fallback_base_url": DEFAULT_REMOTE_API_BASE_URL,
        "manifest_url": DEFAULT_MANIFEST_URL,
        "model": "banano",
        "image_size": "2k",
        "aspect_ratio": "Auto",
        "verify_ssl": "false",
        "connect_timeout_sec": "30",
        "read_timeout_sec": "300",
        "upload_dir": "shortlinks/qr",
        "auto_update": "true",
        "force_update_on_startup": "false",
        "always_sync_files": "true",
        "enable_oss": "true",
        "force_hd": "true",
        "veo_poll_interval_sec": "8",
        "veo_poll_timeout_sec": "1800",
        "veo_resolution": "1080p",
        "veo_aspect_ratio": "16:9",
        "veo_duration_seconds": "8",
        "veo_number_of_videos": "1",
    }

    for key, value in defaults.items():
        if key not in sec or str(sec.get(key, "")).strip() == "":
            sec[key] = value
            changed = True

    current_base_url = str(sec.get("base_url", "")).strip()
    if current_base_url in LEGACY_API_BASE_URLS:
        sec["base_url"] = DEFAULT_REMOTE_API_BASE_URL
        changed = True

    current_manifest_url = str(sec.get("manifest_url", "")).strip()
    if not current_manifest_url:
        sec["manifest_url"] = DEFAULT_MANIFEST_URL
        changed = True

    if changed:
        save_config(cfg)
        _log("INFO", f"已修复/补全 config.ini: {CONFIG_PATH}")


def get_manifest_url_from_config() -> str:
    cfg = load_config()
    url = str(cfg["banana"].get("manifest_url", "")).strip()
    if not url:
        url = DEFAULT_MANIFEST_URL
    return url


def _request_get(url: str, *, timeout: float, verify_ssl: bool, binary: bool = False) -> Any:
    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": f"HrioDesignPluginUpdater/8.1.4?ts={int(time.time())}",
    }

    cache_buster = f"_banana_ts={int(time.time() * 1000)}"
    sep = "&" if "?" in url else "?"
    final_url = f"{url}{sep}{cache_buster}"

    resp = requests.get(final_url, timeout=timeout, verify=verify_ssl, headers=headers)
    resp.raise_for_status()

    return resp.content if binary else resp.json()


def fetch_remote_manifest() -> Dict[str, Any] | None:
    cfg = load_config()
    sec = cfg["banana"]

    manifest_url = get_manifest_url_from_config()
    verify_ssl = _cfg_bool(sec.get("verify_ssl", "false"), False)
    timeout = _cfg_float(sec.get("connect_timeout_sec", "30"), 30.0)

    if not manifest_url:
        _log("WARN", "manifest_url 为空，无法更新")
        return None

    try:
        _log("INFO", f"正在请求远端 manifest: {manifest_url}")
        data = _request_get(manifest_url, timeout=timeout, verify_ssl=verify_ssl, binary=False)
        if not isinstance(data, dict):
            _log("WARN", "远端 manifest 不是 JSON 对象")
            return None

        _log(
            "OK",
            f"远端 manifest 获取成功: plugin_version={data.get('plugin_version')}, schema_version={data.get('schema_version')}",
        )
        return data
    except Exception as e:
        _log("ERR", f"远端 manifest 请求失败: {manifest_url} | {type(e).__name__}: {e}")
        state = load_state()
        state["last_error"] = f"manifest fetch failed: {type(e).__name__}: {e}"
        state["last_update_status"] = "manifest_fetch_failed"
        save_state(state)
        return None


def backup_file(path: str) -> None:
    if not os.path.exists(path):
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    rel_name = os.path.relpath(path, MODULE_DIR).replace("\\", "__").replace("/", "__")
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"{ts}_{rel_name}")

    try:
        shutil.copy2(path, backup_path)
    except Exception as e:
        _log("WARN", f"备份失败，继续覆盖: {path} | {e}")


def download_and_replace_file(rel_path: str, url: str, verify_ssl: bool, timeout: float) -> Tuple[str, bool]:
    rel_path = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel_path:
        raise ValueError("rel_path 为空")

    if ".." in rel_path.split("/"):
        raise ValueError(f"非法相对路径: {rel_path}")

    local_path = os.path.join(MODULE_DIR, rel_path)
    local_dir = os.path.dirname(local_path)
    if local_dir:
        os.makedirs(local_dir, exist_ok=True)

    content = _request_get(url, timeout=timeout, verify_ssl=verify_ssl, binary=True)
    remote_sha = _sha256_bytes(content)

    if os.path.exists(local_path):
        local_sha = _sha256_file(local_path)
        if local_sha == remote_sha:
            return remote_sha, False

    backup_file(local_path)

    tmp_path = f"{local_path}.tmp"
    with open(tmp_path, "wb") as f:
        f.write(content)

    os.replace(tmp_path, local_path)
    return remote_sha, True


def merge_manifest(base: Dict[str, Any], remote: Dict[str, Any] | None) -> Dict[str, Any]:
    if not remote:
        return _deep_copy(base)

    out = _deep_copy(base)
    _deep_merge_inplace(out, remote)

    if not out.get("config_defaults"):
        out["config_defaults"] = {}

    out["config_defaults"].setdefault("manifest_url", DEFAULT_MANIFEST_URL)

    if not out.get("files"):
        out["files"] = {}

    return out


def _remote_is_newer(remote_manifest: Dict[str, Any], local_manifest: Dict[str, Any]) -> bool:
    remote_plugin = remote_manifest.get("plugin_version", "0.0.0")
    local_plugin = local_manifest.get("plugin_version", "0.0.0")

    remote_schema = int(remote_manifest.get("schema_version", 0) or 0)
    local_schema = int(local_manifest.get("schema_version", 0) or 0)

    if _parse_version(remote_plugin) > _parse_version(local_plugin):
        return True

    if remote_schema > local_schema:
        return True

    return False


def _apply_files_from_manifest(manifest: Dict[str, Any], *, reason: str = "") -> Dict[str, Any]:
    files = manifest.get("files") or {}
    if not isinstance(files, dict) or not files:
        _log("WARN", "manifest.files 为空，没有可同步文件")
        return {}

    cfg = load_config()
    sec = cfg["banana"]

    verify_ssl = _cfg_bool(sec.get("verify_ssl", "false"), False)
    timeout = _cfg_float(sec.get("connect_timeout_sec", "30"), 30.0)

    state = load_state()
    file_state = state.setdefault("files", {})

    result: Dict[str, Any] = {}
    updated_count = 0
    checked_count = 0
    failed_count = 0

    for rel_path, meta in files.items():
        if not isinstance(meta, dict):
            continue

        url = str(meta.get("url", "")).strip()
        if not url:
            continue

        checked_count += 1

        try:
            sha, changed = download_and_replace_file(rel_path, url, verify_ssl, timeout)
            if changed:
                updated_count += 1
                _log("OK", f"已更新文件: {rel_path}")
            else:
                _log("INFO", f"文件未变化: {rel_path}")

            file_state[rel_path] = {
                "url": url,
                "sha256": sha,
                "updated_at": int(time.time()),
                "changed": bool(changed),
                "reason": reason,
            }

            result[rel_path] = {
                "ok": True,
                "changed": bool(changed),
                "sha256": sha,
                "url": url,
            }

        except Exception as e:
            failed_count += 1
            err = f"{type(e).__name__}: {e}"
            _log("ERR", f"文件更新失败: {rel_path} | {url} | {err}")

            file_state[rel_path] = {
                "url": url,
                "error": err,
                "updated_at": int(time.time()),
                "changed": False,
                "reason": reason,
            }

            result[rel_path] = {
                "ok": False,
                "changed": False,
                "error": err,
                "url": url,
            }

    state["last_check_ts"] = int(time.time())
    state["last_update_status"] = "done"
    state["last_error"] = "" if failed_count == 0 else f"{failed_count} files failed"
    save_state(state)

    _log(
        "OK",
        f"文件同步完成: checked={checked_count}, updated={updated_count}, failed={failed_count}",
    )

    return result


def apply_core_files(remote_manifest: Dict[str, Any]) -> None:
    _apply_files_from_manifest(remote_manifest, reason="core")


def apply_non_core_files(remote_manifest: Dict[str, Any]) -> None:
    _apply_files_from_manifest(remote_manifest, reason="non_core")


def update_from_remote() -> Dict[str, Any]:
    migrate_config_ini()

    cfg = load_config()
    sec = cfg["banana"]

    auto_update = _cfg_bool(sec.get("auto_update", "true"), True)
    force_update = _cfg_bool(sec.get("force_update_on_startup", "false"), False)
    always_sync_files = _cfg_bool(sec.get("always_sync_files", "true"), True)

    local_manifest = load_local_manifest()
    state = load_state()

    if not auto_update:
        _log("INFO", "auto_update=false，跳过远端更新")
        return local_manifest

    remote_manifest = fetch_remote_manifest()
    if not remote_manifest:
        _log("WARN", f"未获取到远端 manifest，继续使用本地版本: {local_manifest.get('plugin_version')}")
        return local_manifest

    remote_plugin = str(remote_manifest.get("plugin_version", "0.0.0"))
    remote_schema = int(remote_manifest.get("schema_version", 0) or 0)
    local_plugin = str(local_manifest.get("plugin_version", "0.0.0"))
    local_schema = int(local_manifest.get("schema_version", 0) or 0)

    effective_manifest = merge_manifest(local_manifest, remote_manifest)

    remote_newer = _remote_is_newer(remote_manifest, local_manifest)
    should_write_manifest = force_update or remote_newer or effective_manifest != local_manifest

    state["last_manifest_url"] = get_manifest_url_from_config()
    state["last_remote_plugin_version"] = remote_plugin
    state["last_remote_schema_version"] = remote_schema

    if should_write_manifest:
        _write_json(LOCAL_MANIFEST_PATH, effective_manifest)
        _log(
            "OK",
            f"manifest 已写入本地: local={local_plugin}/{local_schema} -> remote={remote_plugin}/{remote_schema}",
        )
    else:
        _log(
            "INFO",
            f"manifest 版本未提升: local={local_plugin}/{local_schema}, remote={remote_plugin}/{remote_schema}",
        )

    if force_update or remote_newer or always_sync_files:
        reason = "force" if force_update else ("version_newer" if remote_newer else "always_sync_files")
        _apply_files_from_manifest(effective_manifest, reason=reason)
    else:
        _log("INFO", "版本未提升且 always_sync_files=false，跳过文件同步")

    state = load_state()
    state["plugin_version"] = str(effective_manifest.get("plugin_version", remote_plugin))
    state["schema_version"] = int(effective_manifest.get("schema_version", remote_schema) or 0)
    state["pending_second_stage"] = False
    state["pending_plugin_version"] = ""
    state["pending_schema_version"] = 0
    state["last_check_ts"] = int(time.time())
    state["last_manifest_url"] = get_manifest_url_from_config()
    state["last_remote_plugin_version"] = remote_plugin
    state["last_remote_schema_version"] = remote_schema
    save_state(state)

    return effective_manifest


def load_effective_manifest() -> Dict[str, Any]:
    migrate_config_ini()
    return load_local_manifest()
