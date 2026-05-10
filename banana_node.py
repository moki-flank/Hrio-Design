# FILE: banana_node.py
from __future__ import annotations

import base64
import configparser
import json
import os
import random
import re
import shutil
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from typing import Any, Dict, List, Tuple

import numpy as np
import requests
import torch
from PIL import Image

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)

try:
    from banana_logger import logger
except Exception:
    class _FallbackLogger:
        def info(self, m): print(f"[INFO] {m}", flush=True)
        def success(self, m): print(f"[OK] {m}", flush=True)
        def warning(self, m): print(f"[WARN] {m}", flush=True)
        def error(self, m): print(f"[ERR] {m}", flush=True)
        def summary(self, t, d):
            print(f"\n===== {t} =====", flush=True)
            for k, v in (d or {}).items():
                print(f"{k}: {v}", flush=True)
            print("", flush=True)

    logger = _FallbackLogger()

try:
    from banana_update import load_effective_manifest
except Exception:
    def load_effective_manifest() -> Dict[str, Any]:
        path = os.path.join(MODULE_DIR, "banana_manifest.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


try:
    from server import PromptServer
    _HAS_PROMPT_SERVER = True
except Exception:
    PromptServer = None
    _HAS_PROMPT_SERVER = False

try:
    from aiohttp import web as aiohttp_web
except Exception:
    aiohttp_web = None


_TIMEOUT_IMAGE = 300
_DL_TIMEOUT = 120
_QUICK_FAILOVER_WINDOW_SEC = 5.0
_DEFAULT_FALLBACK_BASE_URL = "https://zheshihouduan.tenx-jingli.cloud/api"
AUTOMATION_HISTORY_FILE = "banana_automation_history.json"
RUNTIME_RESULTS_FILE = "banana_runtime_results.json"
_AUTOMATION_HISTORY_LOCK = threading.Lock()
_RUNTIME_RESULTS_LOCK = threading.Lock()
_AUTOMATION_HISTORY_MAX_ITEMS = 500
_RUNTIME_RESULTS_MAX_GROUPS = 500
_RUNTIME_RESULTS_MAX_VIDEOS = 200

_MEDIA_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+?\.(?:png|jpg|jpeg|webp|gif|bmp)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)

_VIDEO_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+?\.(?:mp4|mov|webm|m4v)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)

_RUNTIME_ROUTE_STATE = {
    "prefer_fallback": False,
    "last_reason": "",
}


def _load_config() -> Dict[str, str]:
    cfg = configparser.ConfigParser()
    ini = os.path.join(MODULE_DIR, "config.ini")
    if os.path.exists(ini):
        cfg.read(ini, encoding="utf-8")

    out: Dict[str, str] = {}
    if cfg.has_section("banana"):
        for k, v in cfg["banana"].items():
            out[k] = v
    return out


_CFG = _load_config()
_MANIFEST = load_effective_manifest() or {}
_NODE = _MANIFEST.get("node", {}) or {}
_ENUM_SOURCES = _NODE.get("enum_sources", {}) or {}
_MODEL_DISPLAY_TO_ACTUAL = _NODE.get("model_map") or _ENUM_SOURCES.get("model_map") or {
    "banano2": "banano",
    "banano-pro": "banano-pro",
    "gemini3.1-pro": "gemini3.1-pro",
}

_REMOTE_FIRST_CONFIG_KEYS = {
    "base_url",
    "fallback_base_url",
    "model",
    "image_size",
    "aspect_ratio",
    "verify_ssl",
    "connect_timeout_sec",
    "read_timeout_sec",
    "upload_dir",
    "enable_oss",
    "compress_images",
    "force_hd",
}


def _cfg(k: str, d: str = "") -> str:
    return str(_CFG.get(k, d))


def _manifest_cfg(k: str, d: str = "") -> str:
    return str((_MANIFEST.get("config_defaults", {}) or {}).get(k, d))


def _cfg_or_manifest(k: str, fallback: str = "", prefer_remote: Any = None) -> str:
    if prefer_remote is None:
        prefer_remote = k in _REMOTE_FIRST_CONFIG_KEYS

    if prefer_remote:
        remote = _manifest_cfg(k, "").strip()
        if remote:
            return remote

        local = _cfg(k, "").strip()
        if local:
            return local

        return str(fallback)

    local = _cfg(k, "").strip()
    if local:
        return local

    remote = _manifest_cfg(k, "").strip()
    if remote:
        return remote

    return str(fallback)


def _value_as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _cfg_bool(k: str, default: bool = False) -> bool:
    return _value_as_bool(_cfg_or_manifest(k, "true" if default else "false"), default)


def _cfg_int(k: str, default: int) -> int:
    try:
        return int(str(_cfg_or_manifest(k, str(default))).strip())
    except Exception:
        return default


def _normalize_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def _primary_base_url() -> str:
    return _normalize_base_url(_cfg_or_manifest("base_url", ""))


def _fallback_base_url() -> str:
    return _normalize_base_url(
        _cfg_or_manifest("fallback_base_url", _DEFAULT_FALLBACK_BASE_URL)
        or _DEFAULT_FALLBACK_BASE_URL
    )


def _prefer_fallback_route() -> bool:
    return bool(_RUNTIME_ROUTE_STATE.get("prefer_fallback"))


def _activate_fallback(reason: str) -> None:
    if not _fallback_base_url():
        return

    if not _RUNTIME_ROUTE_STATE.get("prefer_fallback"):
        logger.warning(f"检测到主域名快速报错，切换到兜底域名: {_fallback_base_url()}")

    _RUNTIME_ROUTE_STATE["prefer_fallback"] = True
    _RUNTIME_ROUTE_STATE["last_reason"] = str(reason or "")

    if reason:
        logger.warning(f"切换原因: {reason}")


def _public_api_root(use_fallback: bool = False) -> str:
    base = _fallback_base_url() if (use_fallback or _prefer_fallback_route()) else _primary_base_url()
    base = _normalize_base_url(base)

    if base.endswith("/oss"):
        base = base[:-4]

    return base


def _base_api_root(enable_oss: bool = False, use_fallback: bool = False) -> str:
    base = _public_api_root(use_fallback=use_fallback)
    if not base:
        return ""

    if enable_oss and not base.endswith("/oss"):
        return f"{base}/oss"

    return base


def _uploads_presign_url(use_fallback: bool = False) -> str:
    base = _public_api_root(use_fallback=use_fallback)
    return f"{base}/uploads/presign" if base else ""


def _gemini_url(model: str, enable_oss: bool = False, use_fallback: bool = False) -> str:
    base = _base_api_root(enable_oss=enable_oss, use_fallback=use_fallback)
    return f"{base}/v1beta/models/{model}:generateContent" if base else ""


def _video_generate_url(
    model: str,
    action: str = "generateContent",
    enable_oss: bool = True,
    use_fallback: bool = False,
) -> str:
    """
    生视频接口 URL。

    兼容两种后端格式：
    - /v1beta/models/{model}:generateContent
    - /v1beta/models/{model}:predictLongRunning

    enable_oss=True 时会沿用当前项目的 /oss 路由规则。
    """
    base = _base_api_root(enable_oss=enable_oss, use_fallback=use_fallback)
    if not base:
        return ""

    action = str(action or "generateContent").strip().lstrip(":/") or "generateContent"
    return f"{base}/v1beta/models/{model}:{action}"


def _operation_get_url(operation_name: str, use_fallback: bool = False) -> str:
    """
    视频长任务轮询 URL。

    后端可能返回：
    - 完整 URL
    - operations/xxx
    - models/{model}/operations/xxx
    - v1beta/...
    这里全部归一化成可 GET 的地址。
    """
    name = str(operation_name or "").strip()
    if not name:
        return ""

    if name.startswith("http://") or name.startswith("https://"):
        return name

    base = _base_api_root(enable_oss=True, use_fallback=use_fallback)
    if not base:
        return ""

    name = name.lstrip("/")
    if name.startswith("v1beta/"):
        return f"{base}/{name}"

    return f"{base}/v1beta/{name}"


def _video_model_options() -> List[str]:
    options = _enum_source_options("video_model_map", [])

    if options:
        return options

    cfg_value = _cfg_or_manifest("video_model", "").strip()
    manifest_value = str((_MANIFEST.get("video", {}) or {}).get("default_model") or "").strip()

    out: List[str] = []
    for value in [cfg_value, manifest_value, "veo3.1"]:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)

    return out or ["veo3.1"]


def _manual_video_model_default() -> str:
    options = _video_model_options()

    raw = (
        str((_MANIFEST.get("video", {}) or {}).get("default_model") or "").strip()
        or _cfg_or_manifest("video_model", "").strip()
        or _cfg_or_manifest("model_video", "").strip()
        or "veo3.1"
    )

    display = _enum_source_display("video_model_map", raw, raw)
    if display in options:
        return display

    return options[0] if options else "veo3.1"


def _extract_urls_from_video_text(text: str) -> List[str]:
    if not text:
        return []

    return [m.group(0).rstrip(").,，。]】\"'") for m in _VIDEO_URL_RE.finditer(str(text))]


def _looks_like_video_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False

    return bool(_VIDEO_URL_RE.search(text))


def _walk_extract_video_urls(obj: Any, urls: List[str]) -> None:
    """
    从各种 Gemini/代理后端响应里递归提取视频 URL。
    支持 mp4 / mov / webm / m4v。
    """
    if obj is None:
        return

    if isinstance(obj, dict):
        file_data = obj.get("fileData") or obj.get("file_data")
        if isinstance(file_data, dict):
            uri = file_data.get("fileUri") or file_data.get("uri") or file_data.get("url")
            if isinstance(uri, str):
                urls.extend(_extract_urls_from_video_text(uri))
                if _looks_like_video_url(uri):
                    urls.append(uri.strip())

        for key in (
            "mp4url",
            "mp4Url",
            "videoUrl",
            "video_url",
            "downloadUrl",
            "download_url",
            "oss_url",
            "ossUrl",
            "fileUri",
            "public_url",
            "url",
            "uri",
        ):
            value = obj.get(key)
            if isinstance(value, str):
                urls.extend(_extract_urls_from_video_text(value))
                if _looks_like_video_url(value):
                    urls.append(value.strip())

        text = obj.get("text")
        if isinstance(text, str) and text.strip():
            urls.extend(_extract_urls_from_video_text(text))

        for value in obj.values():
            _walk_extract_video_urls(value, urls)

    elif isinstance(obj, list):
        for item in obj:
            _walk_extract_video_urls(item, urls)

    elif isinstance(obj, str):
        urls.extend(_extract_urls_from_video_text(obj))


def _should_failover_status(status_code: int) -> bool:
    """
    只对真正可能是线路/服务端问题的状态码切换兜底。
    400/401/403/404 这类业务错误不能触发切线；否则像 Veo generateContent 的 400
    会把后续正确的 predictLongRunning 请求错误地打到 fallback 路由。
    """
    try:
        code = int(status_code)
    except Exception:
        return False
    return code in {408, 409, 425, 429} or code >= 500


def _candidate_urls(builder, *args, **kwargs) -> List[Tuple[str, str, bool]]:
    primary = builder(*args, use_fallback=False, **kwargs)
    fallback = builder(*args, use_fallback=True, **kwargs)

    order = [
        ("fallback", fallback, True),
        ("primary", primary, False),
    ] if _prefer_fallback_route() else [
        ("primary", primary, False),
        ("fallback", fallback, True),
    ]

    seen = set()
    out = []

    for name, url, is_fallback in order:
        url = str(url or "").strip()
        if not url or url in seen:
            continue

        seen.add(url)
        out.append((name, url, is_fallback))

    return out


def _request_json_with_failover(
    method: str,
    builder,
    *,
    builder_args: Tuple[Any, ...] = (),
    builder_kwargs: Dict[str, Any] | None = None,
    headers: Dict[str, str],
    json_payload: Dict[str, Any] | None,
    timeout: int,
    action_name: str,
) -> Tuple[requests.Response, Dict[str, Any], str, str]:
    """
    HRIO ??????????

    ?? AI ????? Windows ComfyUI / requests ????
    SSLError: UNEXPECTED_EOF_WHILE_READING

    ????
    - ????? 5 ???????
    - ?? requests.Session()
    - trust_env=False??? Windows ????????
    - Connection: close????????
    - ? SSLError / ConnectionError ?????
    """
    builder_kwargs = builder_kwargs or {}
    verify_ssl = _cfg_bool("verify_ssl", False)

    req_headers = dict(headers or {})
    req_headers.setdefault("Accept", "application/json")
    req_headers.setdefault("User-Agent", "HrioDesignComfyUI/8.1 HRIO_REQUEST_FIX")
    req_headers["Connection"] = "close"

    candidates = _candidate_urls(builder, *builder_args, **builder_kwargs)

    if not candidates:
        raise RuntimeError(f"{action_name} ????????")

    last_error: Exception | None = None

    for attempt in range(1, 6):
        for route_name, url, is_fallback in candidates:
            t0 = time.time()

            try:
                logger.info(f"[HRIO_REQUEST_FIX] {action_name} -> ?{attempt}?, ??={route_name}, url={url}")

                sess = requests.Session()
                sess.trust_env = False

                resp = sess.request(
                    method,
                    url,
                    headers=req_headers,
                    json=json_payload,
                    timeout=(30, timeout),
                    verify=verify_ssl,
                )

                elapsed = time.time() - t0

                try:
                    data = resp.json()
                except Exception:
                    data = {"raw_text": resp.text[:3000]}

                logger.info(
                    f"[HRIO_REQUEST_FIX] {action_name} <- ??={route_name}, "
                    f"HTTP {resp.status_code}, ?? {elapsed:.1f}s"
                )

                if resp.status_code >= 400:
                    err = RuntimeError(f"HTTP {resp.status_code}: {data}")
                    last_error = err

                    if _should_failover_status(resp.status_code):
                        logger.warning(
                            f"[HRIO_REQUEST_FIX] {action_name} HTTP {resp.status_code}?????"
                        )
                        time.sleep(min(2 * attempt, 10))
                        continue

                    raise err

                if isinstance(data, dict) and data.get("error"):
                    err = RuntimeError(json.dumps(data, ensure_ascii=False)[:2500])
                    last_error = err
                    logger.warning(
                        f"[HRIO_REQUEST_FIX] {action_name} ???? error?????: {err}"
                    )
                    time.sleep(min(2 * attempt, 10))
                    continue

                return resp, data, route_name, url

            except Exception as e:
                elapsed = time.time() - t0
                last_error = e

                logger.error(
                    f"[HRIO_REQUEST_FIX] {action_name} {route_name} ???"
                    f"?{attempt}???? {elapsed:.1f}s: {type(e).__name__}: {e}"
                )

                time.sleep(min(2 * attempt, 10))

    raise RuntimeError(f"{action_name} ??????: {last_error}")



def _enum_source_options(source_name: str, fallback: List[str]) -> List[str]:
    src = _ENUM_SOURCES.get(source_name)
    if isinstance(src, dict) and src:
        return list(src.keys())
    return fallback


def _enum_source_display(source_name: str, value: Any, fallback: str) -> str:
    src = _ENUM_SOURCES.get(source_name)
    raw = str(value or "").strip()

    if isinstance(src, dict) and src:
        if raw in src:
            return raw

        raw_l = raw.lower()
        for display, actual in src.items():
            if str(actual).strip().lower() == raw_l:
                return str(display)

    return fallback


def _enum_actual(source_name: str, value: Any) -> str:
    src = _ENUM_SOURCES.get(source_name)
    raw = str(value or "").strip()

    if isinstance(src, dict) and src:
        if raw in src:
            return str(src[raw])

        raw_l = raw.lower()
        for display, actual in src.items():
            if str(display).strip().lower() == raw_l:
                return str(actual)

    return raw


def _manual_model_default() -> str:
    options = _enum_source_options("model_map", ["banano2", "banano-pro", "gemini3.1-pro"])
    return _enum_source_display("model_map", _cfg_or_manifest("model", "banano"), options[0])


def _manual_image_size_default() -> str:
    options = _enum_source_options("image_size_options", ["1K", "2K", "4K", "8K（默认16:9）"])
    return _enum_source_display("image_size_options", _cfg_or_manifest("image_size", "2K"), "2K")


def _manual_aspect_ratio_default(default_value: str = "Auto") -> str:
    options = _enum_source_options(
        "aspect_ratio_options",
        ["Auto", "1:1 (方形)", "3:4 (竖屏标准)", "9:16 (竖屏/手机)", "16:9 (横屏宽幅)"],
    )
    return _enum_source_display("aspect_ratio_options", default_value, "Auto")


def _video_resolution_options() -> List[str]:
    options = _enum_source_options("video_resolution_options", ["1080p", "720p"])
    out: List[str] = []
    for value in list(options or []) + ["1080p", "720p"]:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out or ["1080p", "720p"]


def _manual_video_resolution_default() -> str:
    options = _video_resolution_options()
    raw = (
        str((_MANIFEST.get("video", {}) or {}).get("default_resolution") or "").strip()
        or _cfg_or_manifest("veo_resolution", "1080p").strip()
        or "1080p"
    )
    if raw in options:
        return raw
    raw_l = raw.lower()
    for item in options:
        if item.lower() == raw_l:
            return item
    if "1080" in raw_l and "1080p" in options:
        return "1080p"
    if ("780" in raw_l or "720" in raw_l) and "720p" in options:
        return "720p"
    return options[0]


def _video_aspect_ratio_options() -> List[str]:
    options = ["16:9 (横屏宽幅)", "9:16 (竖屏/手机)"]
    configured = _enum_source_options("video_aspect_ratio_options", [])
    out: List[str] = []
    for value in list(configured or []) + options:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out or options


def _manual_video_aspect_ratio_default() -> str:
    options = _video_aspect_ratio_options()
    raw = (
        str((_MANIFEST.get("video", {}) or {}).get("default_aspect_ratio") or "").strip()
        or _cfg_or_manifest("veo_aspect_ratio", "16:9").strip()
        or "16:9"
    )
    display = _enum_source_display("aspect_ratio_options", raw, raw)
    if display in options:
        return display
    raw_l = str(raw or "").lower()
    if "9:16" in raw_l or "vertical" in raw_l or "portrait" in raw_l or "竖" in raw_l:
        for item in options:
            if "9:16" in item or "竖" in item:
                return item
    if "16:9" in raw_l or "horizontal" in raw_l or "landscape" in raw_l or "横" in raw_l:
        for item in options:
            if "16:9" in item or "横" in item:
                return item
    return options[0]


def _normalize_video_resolution(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = _manual_video_resolution_default()
    low = raw.lower()
    if "1080" in low:
        return "1080p"
    # 后端 Veo 协议当前合法值是 720p / 1080p / 4k。
    # UI 里给用户保留 720p 选项，但请求时按 720p 兼容发送，避免后端 400。
    if "780" in low or "720" in low:
        return "720p"
    if "4k" in low or "4K" in raw:
        return "4k"
    return raw or "1080p"


def _normalize_video_aspect_ratio(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = _manual_video_aspect_ratio_default()
    actual = _enum_actual("aspect_ratio_options", raw)
    low = str(actual or raw).strip().lower()
    if "9:16" in low or "portrait" in low or "vertical" in low or "竖" in low:
        return "9:16"
    if "16:9" in low or "landscape" in low or "horizontal" in low or "横" in low:
        return "16:9"
    return "16:9"


def _guess_mime_from_url(url: str, default: str = "image/png") -> str:
    u = str(url or "").lower().split("?", 1)[0]

    if u.endswith(".jpg") or u.endswith(".jpeg"):
        return "image/jpeg"
    if u.endswith(".webp"):
        return "image/webp"
    if u.endswith(".gif"):
        return "image/gif"
    if u.endswith(".bmp"):
        return "image/bmp"

    return default


def _pil_to_tensor(img: Image.Image) -> torch.Tensor:
    arr = np.array(img.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def _tensor_to_png(t: torch.Tensor) -> bytes:
    arr = (t.detach().cpu().clamp(0, 1).numpy() * 255).astype("uint8")
    img = Image.fromarray(arr)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _error_img(msg: str) -> torch.Tensor:
    from PIL import ImageDraw

    img = Image.new("RGB", (1200, 220), (140, 32, 32))
    draw = ImageDraw.Draw(img)
    draw.text((16, 16), str(msg or "")[:260], fill=(255, 255, 255))
    return _pil_to_tensor(img)


def _download_binary(url: str) -> bytes:
    verify_ssl = _cfg_bool("verify_ssl", False)
    proxies = {"http": None, "https": None}

    resp = requests.get(url, timeout=_DL_TIMEOUT, proxies=proxies, verify=verify_ssl)
    resp.raise_for_status()
    return resp.content


def _download_image(url: str) -> Image.Image:
    raw = _download_binary(url)
    return Image.open(BytesIO(raw)).convert("RGB")


def _sanitize_upload_dir(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")

    if not raw:
        return "uploads/images"

    parts = [p for p in raw.split("/") if p and p not in {".", ".."}]
    return "/".join(parts) if parts else "uploads/images"


def _presign_and_upload_one_image(api_key: str, png_bytes: bytes, index: int, upload_dir: str) -> str:
    """
    ComfyUI ????????
    1. POST ???? /uploads/presign ?? COS ?? PUT ??
    2. PUT ?????? upload_url
    3. ?? public_url ?????????

    ????
    - ???? _request_json_with_failover??? 5 ? SSLEOF ????
    - presign ????????
    - ?? requests.Session ? trust_env=False??? Windows ????????
    - ?????? headers / upload_headers / required_headers
    - COS PUT ????? 200 / 201 / 204
    """
    primary_url = _uploads_presign_url(use_fallback=False)
    fallback_url = _uploads_presign_url(use_fallback=True)

    urls = []
    for u in [primary_url, fallback_url, primary_url]:
        u = str(u or "").strip()
        if u and u not in urls:
            urls.append(u)

    if not urls:
        raise RuntimeError("??? base_url????? /uploads/presign")

    payload = {
        "filename": f"comfyui_ref_{index}.png",
        "content_type": "image/png",
        "dir": _sanitize_upload_dir(upload_dir),
        "expires_in": 1800,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
        "User-Agent": "HrioDesignComfyUI/8.1 presign-uploader",
        "X-API-Key": api_key,
    }

    verify_ssl = _cfg_bool("verify_ssl", False)
    data = None
    last_error = None
    used_url = ""
    used_route = "primary"

    for attempt in range(1, 5):
        for url in urls:
            used_url = url
            used_route = "fallback" if fallback_url and url == fallback_url and fallback_url != primary_url else "primary"
            t0 = time.time()

            try:
                logger.info(f"[HRIO_UPLOAD_FIX] ??? {index} /uploads/presign -> ?{attempt}?, ??={used_route}, url={url}")

                sess = requests.Session()
                sess.trust_env = False

                resp = sess.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=(30, _TIMEOUT_IMAGE),
                    verify=verify_ssl,
                )

                elapsed = time.time() - t0

                try:
                    body = resp.json()
                except Exception:
                    body = {"raw_text": resp.text[:2000]}

                logger.info(f"[HRIO_UPLOAD_FIX] ??? {index} /uploads/presign <- HTTP {resp.status_code}, ?? {elapsed:.1f}s")

                if resp.status_code >= 400:
                    last_error = RuntimeError(f"/uploads/presign HTTP {resp.status_code}: {body}")
                    logger.error(f"[HRIO_UPLOAD_FIX] ??? {index} presign ??: {last_error}")
                    time.sleep(min(1.5 * attempt, 5))
                    continue

                if not isinstance(body, dict):
                    last_error = RuntimeError(f"/uploads/presign ???? JSON ??: {body}")
                    logger.error(f"[HRIO_UPLOAD_FIX] {last_error}")
                    time.sleep(min(1.5 * attempt, 5))
                    continue

                data = body.get("data") if isinstance(body.get("data"), dict) else body
                break

            except Exception as e:
                elapsed = time.time() - t0
                last_error = e
                logger.error(
                    f"[HRIO_UPLOAD_FIX] ??? {index} /uploads/presign ???"
                    f"?{attempt}???? {elapsed:.1f}s: {type(e).__name__}: {e}"
                )
                time.sleep(min(1.5 * attempt, 5))

        if data:
            break

    if not data:
        raise RuntimeError(f"[HRIO_UPLOAD_FIX] ??? {index} /uploads/presign ??????: {last_error}")

    upload_url = str(
        data.get("upload_url")
        or data.get("uploadUrl")
        or data.get("put_url")
        or data.get("putUrl")
        or data.get("signed_url")
        or data.get("signedUrl")
        or data.get("presigned_url")
        or ""
    ).strip()

    public_url = str(
        data.get("public_url")
        or data.get("publicUrl")
        or data.get("file_url")
        or data.get("fileUrl")
        or data.get("url")
        or ""
    ).strip()

    required_headers = (
        data.get("required_headers")
        or data.get("headers")
        or data.get("upload_headers")
        or data.get("uploadHeaders")
        or {}
    )

    content_type = str(data.get("content_type") or data.get("contentType") or "image/png").strip() or "image/png"

    if not upload_url:
        raise RuntimeError(f"[HRIO_UPLOAD_FIX] /uploads/presign ??? upload_url: {data}")

    if not public_url:
        raise RuntimeError(f"[HRIO_UPLOAD_FIX] /uploads/presign ??? public_url/url: {data}")

    put_headers = {
        "Connection": "close",
        "User-Agent": "HrioDesignComfyUI/8.1 cos-put",
    }

    if isinstance(required_headers, dict):
        for k, v in required_headers.items():
            if v is None:
                continue

            key = str(k).strip()
            low = key.lower()

            if low in {
                "host",
                "content-length",
                "connection",
                "accept-encoding",
                "origin",
                "referer",
                "authorization",
                "x-api-key",
            }:
                continue

            put_headers[key] = str(v)

    put_headers.setdefault("Content-Type", content_type)

    logger.info(f"[HRIO_UPLOAD_FIX] ??? {index}: presign ??")
    logger.info(f"[HRIO_UPLOAD_FIX] ??? {index}: upload_url={upload_url.split('?')[0]}")
    logger.info(f"[HRIO_UPLOAD_FIX] ??? {index}: public_url={public_url}")
    logger.info(f"[HRIO_UPLOAD_FIX] ??? {index}: ?? COS PUT ????={used_route}")

    last_put_error = None

    for attempt in range(1, 4):
        try:
            sess = requests.Session()
            sess.trust_env = False

            put_resp = sess.put(
                upload_url,
                headers=put_headers,
                data=png_bytes,
                timeout=(30, _TIMEOUT_IMAGE),
                verify=verify_ssl,
            )

            if put_resp.status_code in (200, 201, 204):
                logger.success(f"[HRIO_UPLOAD_FIX] ??? {index}: ???? -> {public_url}")
                return public_url

            last_put_error = RuntimeError(
                f"COS PUT ???? HTTP {put_resp.status_code}: {put_resp.text[:1000]}"
            )
            logger.error(f"[HRIO_UPLOAD_FIX] ??? {index}: PUT ?{attempt}???: {last_put_error}")
            time.sleep(min(1.5 * attempt, 5))

        except Exception as e:
            last_put_error = e
            logger.error(f"[HRIO_UPLOAD_FIX] ??? {index}: PUT ?{attempt}???: {type(e).__name__}: {e}")
            time.sleep(min(1.5 * attempt, 5))

    raise RuntimeError(f"[HRIO_UPLOAD_FIX] ??? {index}: COS PUT ??????: {last_put_error}")



def _collect_reference_tensors_from_kwargs(kwargs: Dict[str, Any], slot_count: int | None = None) -> List[torch.Tensor]:
    if slot_count is None:
        slot_count = int(_NODE.get("optional_image_slots", 10) or 10)

    tensors: List[torch.Tensor] = []

    for i in range(1, int(slot_count) + 1):
        key = f"image_{i}"
        if key in kwargs and kwargs[key] is not None:
            tensors.append(kwargs[key])

    return tensors


def _tensors_to_uploaded_urls(tensors: List[torch.Tensor], api_key: str, upload_dir: str) -> List[str]:
    urls: List[str] = []
    counter = 0

    for t in tensors:
        if t is None:
            continue

        batch = t.detach().cpu()

        if batch.ndim == 3:
            batch = batch.unsqueeze(0)

        for b in range(batch.shape[0]):
            counter += 1
            png_bytes = _tensor_to_png(batch[b])
            urls.append(_presign_and_upload_one_image(api_key, png_bytes, counter, upload_dir))

    return urls


def _upload_reference_images_for_node(kwargs: Dict[str, Any], api_key: str) -> List[str]:
    tensors = _collect_reference_tensors_from_kwargs(kwargs)

    if not tensors:
        return []

    upload_dir = _cfg_or_manifest("upload_dir", "uploads/images")
    logger.info(f"检测到 {len(tensors)} 组参考图，开始上传；上传后的 URL 会被三路并发复用")

    return _tensors_to_uploaded_urls(tensors, api_key, upload_dir)


def _resize_image_batch_to_hw(t: torch.Tensor, height: int, width: int) -> torch.Tensor:
    batch = t.detach().cpu()

    if batch.ndim == 3:
        batch = batch.unsqueeze(0)

    if int(batch.shape[1]) == int(height) and int(batch.shape[2]) == int(width):
        return batch

    x = batch.permute(0, 3, 1, 2)

    x = torch.nn.functional.interpolate(
        x,
        size=(int(height), int(width)),
        mode="bilinear",
        align_corners=False,
    )

    return x.permute(0, 2, 3, 1).clamp(0, 1)


def _cat_image_batches_safe(tensors: List[torch.Tensor]) -> torch.Tensor:
    cleaned: List[torch.Tensor] = []

    for t in tensors:
        if t is None:
            continue

        b = t.detach().cpu()

        if b.ndim == 3:
            b = b.unsqueeze(0)

        cleaned.append(b)

    if not cleaned:
        return _error_img("没有可输出图片")

    max_h = max(int(t.shape[1]) for t in cleaned)
    max_w = max(int(t.shape[2]) for t in cleaned)

    resized = [_resize_image_batch_to_hw(t, max_h, max_w) for t in cleaned]
    return torch.cat(resized, dim=0)


def _first_image_or_error(tensors: List[torch.Tensor], label: str) -> torch.Tensor:
    if not tensors:
        return _error_img(f"{label} 没有图片")

    t = tensors[0].detach().cpu()

    if t.ndim == 3:
        t = t.unsqueeze(0)

    return t




_THREE_VIEW_ORDER = [
    ("front", "正面图"),
    ("side", "侧面图"),
    ("back", "背面图"),
]

_THREE_VIEW_SCOPE_OPTIONS = [
    "全部并发生成",
    "仅重新生成正面",
    "仅重新生成侧面",
    "仅重新生成背面",
]

_THREE_VIEW_SCOPE_MAP = {
    "全部并发生成": ["front", "side", "back"],
    "仅重新生成正面": ["front"],
    "仅重新生成侧面": ["side"],
    "仅重新生成背面": ["back"],
}

_LAST_THREE_VIEW_CACHE: Dict[str, Dict[str, torch.Tensor]] = {}
_LAST_THREE_VIEW_RUNTIME: Dict[str, Dict[str, Any]] = {}
_LAST_THREE_VIEW_LATEST_KEY: str = ""
_LAST_VIDEO_RUNTIME: Dict[str, Dict[str, Any]] = {}
_LAST_VIDEO_LATEST_KEY: str = ""



def _normalize_generate_scope(generate_scope: Any) -> str:
    scope = str(generate_scope or "").strip()
    if scope in _THREE_VIEW_SCOPE_MAP:
        return scope
    return "全部并发生成"


def _cache_key_or_default(cache_key: Any) -> str:
    raw = str(cache_key or "").strip()
    return raw or "banana_three_view_default_cache"


def _get_cached_view(cache_key: Any, view_key: str) -> torch.Tensor | None:
    key = _cache_key_or_default(cache_key)
    bucket = _LAST_THREE_VIEW_CACHE.get(key) or {}
    tensor = bucket.get(view_key)
    if tensor is None:
        return None

    try:
        out = tensor.detach().cpu()
        if out.ndim == 3:
            out = out.unsqueeze(0)
        return out
    except Exception:
        return None


def _set_cached_view(cache_key: Any, view_key: str, tensor: torch.Tensor) -> None:
    key = _cache_key_or_default(cache_key)
    if key not in _LAST_THREE_VIEW_CACHE:
        _LAST_THREE_VIEW_CACHE[key] = {}

    try:
        out = tensor.detach().cpu()
        if out.ndim == 3:
            out = out.unsqueeze(0)
        _LAST_THREE_VIEW_CACHE[key][view_key] = out
    except Exception:
        pass



def _safe_int(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        out = int(float(str(value).strip()))
    except Exception:
        out = int(default)
    if min_value is not None:
        out = max(int(min_value), out)
    if max_value is not None:
        out = min(int(max_value), out)
    return out


def _safe_float(value: Any, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        out = float(str(value).strip())
    except Exception:
        out = float(default)
    if min_value is not None:
        out = max(float(min_value), out)
    if max_value is not None:
        out = min(float(max_value), out)
    return out


def _resolve_retry_options(values: Dict[str, Any]) -> Tuple[bool, int, float]:
    auto_retry = _value_as_bool(values.get("auto_retry_until_success"), True)
    max_retry = _safe_int(values.get("max_retry_per_view", _cfg_or_manifest("max_retry_per_view", "8")), 8, 1, 999)
    retry_interval = _safe_float(values.get("retry_interval_sec", _cfg_or_manifest("retry_interval_sec", "1.5")), 1.5, 0.1, 30.0)
    if not auto_retry:
        max_retry = 1
    return auto_retry, max_retry, retry_interval


def _tensor_to_preview_data_url(tensor: torch.Tensor, max_edge: int = 360) -> str:
    try:
        t = tensor.detach().cpu()
        if t.ndim == 4:
            t = t[0]
        arr = (t.clamp(0, 1).numpy() * 255).astype("uint8")
        img = Image.fromarray(arr).convert("RGB")
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > max_edge:
            scale = max_edge / float(long_edge)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _iter_preview_frames(tensor: Any):
    if tensor is None:
        return
    try:
        t = tensor.detach().cpu().clamp(0, 1)
        if t.ndim == 3:
            yield t
            return
        if t.ndim == 4:
            for i in range(int(t.shape[0])):
                yield t[i]
    except Exception:
        return


def _tensor_frame_to_pil(frame: torch.Tensor) -> Image.Image:
    arr = frame.detach().cpu().clamp(0, 1).numpy()
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[-1] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    arr = (arr * 255).astype(np.uint8)
    if arr.ndim == 2:
        return Image.fromarray(arr).convert("RGB")
    if arr.shape[-1] == 4:
        return Image.fromarray(arr, "RGBA").convert("RGB")
    return Image.fromarray(arr).convert("RGB")


def _save_tensors_for_comfyui_preview(
    tensors: List[Any], label: str = "banana"
) -> List[Dict[str, str]]:
    """
    v8.2.4：把图片写到 ComfyUI output 目录（而非 temp），
    type="output" → 左侧「已生成」媒体资产面板可见。
 
    注意：此函数现在只负责把文件落盘到 output 目录并返回引用；
    _return_images_with_ui_preview 会决定是否把这些引用放进 ui.images。
    自动化模式下 ui.images 仍然填充所有图片（全部进媒体资产），
    但节点底部预览通过 _return_images_with_ui_preview 里的逻辑控制不显示。
    """
    results: List[Dict[str, str]] = []
    try:
        import folder_paths  # type: ignore
        # 写到 output 目录下的 hrio_design 子目录，避免和其他节点混
        base_output = folder_paths.get_output_directory()
        output_dir = os.path.join(base_output, "hrio_design")
        subfolder = "hrio_design"
        image_type = "output"
    except Exception:
        output_dir = os.path.join(MODULE_DIR, "hrio_design_outputs")
        subfolder = ""
        image_type = "output"
 
    os.makedirs(output_dir, exist_ok=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_\-]+", "_", str(label or "banana"))[:48] or "banana"
    prefix = f"{safe_label}_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
 
    index = 0
    for tensor in tensors or []:
        for frame in _iter_preview_frames(tensor):
            try:
                index += 1
                filename = f"{prefix}_{index:02d}.png"
                path = os.path.join(output_dir, filename)
                _tensor_frame_to_pil(frame).save(path, format="PNG", compress_level=1)
                results.append({
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": image_type,
                })
            except Exception as e:
                logger.warning(f"ComfyUI output 图片保存失败，已跳过一帧: {e}")
 
    return results
 
def _return_images_with_ui_preview(
    result_tuple: tuple,
    label: str = "banana",
    *,
    extra_output_paths: List[str] | None = None,  # 自动化时传入全部已保存图片的磁盘路径
) -> dict:
    """
    v8.2.4：
    - OUTPUT_NODE = True 必须返回 {"ui": {...}, "result": (...)}，否则 ComfyUI 卡死。
    - ui.images type="output" → 进左侧媒体资产面板。
    - 节点底部预览：返回空 images 列表，彻底不显示节点底部缩略图。
      媒体资产面板靠 extra_output_paths 里已落盘到 output 目录的文件引用来入库。
    - 自动化模式：调用方把全部序号的输出路径放进 extra_output_paths，
      全部进媒体资产面板；result 元组只携带最后一张张量供下游节点使用。
    """
    # ── 1. 节点底部预览：永远返回空，彻底去掉节点底部图片预览 ──────────────
    ui_images: List[Dict[str, str]] = []
 
    # ── 2. 把已保存到 output 目录的文件注册进媒体资产 ─────────────────────
    #    extra_output_paths 是自动化完成后每组 _save_tensor_image 写出的路径列表
    if extra_output_paths:
        for path in extra_output_paths:
            try:
                ref = _comfyui_media_ref_from_path(path)
                if ref.get("filename") and ref.get("type") == "output":
                    ui_images.append({
                        "filename": ref["filename"],
                        "subfolder": str(ref.get("subfolder") or ""),
                        "type": "output",
                    })
            except Exception as _e:
                logger.warning(f"[_return_images_with_ui_preview] 路径注册失败: {path} | {_e}")
 
    # ── 3. 非自动化（手动单次）：把 result_tuple 里的张量保存到 output 目录 ─
    if not extra_output_paths:
        tensors = [t for t in result_tuple if isinstance(t, __import__("torch").Tensor)]
        if tensors:
            try:
                saved = _save_tensors_for_comfyui_preview(tensors, label=label)
                # 仍然不放进 ui_images，节点底部不显示；但文件已落到 output 目录
                # 让 ComfyUI 的文件扫描机制自然发现（output 目录会被定期扫描）
                # 如果想让它立刻进媒体资产，取消下面注释：
                # ui_images.extend(saved)
                _ = saved  # 文件落盘，媒体资产下次刷新时自动扫描到
            except Exception as _e:
                logger.warning(f"[_return_images_with_ui_preview] 张量保存失败: {_e}")
 
    return {"ui": {"images": ui_images}, "result": tuple(result_tuple)}

def _guess_video_ext_from_value(value: Any, default_ext: str = ".mp4") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default_ext
    text = text.split("?", 1)[0]
    for ext in (".mp4", ".mov", ".webm", ".m4v"):
        if text.endswith(ext):
            return ext
    return default_ext


def _guess_video_mime_from_value(value: Any) -> str:
    ext = _guess_video_ext_from_value(value, ".mp4")
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
    }.get(ext, "video/mp4")



def _save_video_for_comfyui_preview(video_url_or_path: Any, label: str = "banana_video") -> Tuple[List[Dict[str, Any]], str]:
    """
    将远程视频下载到 ComfyUI temp 目录，返回前端 ui.videos 可识别的数据，
    同时返回本地文件路径。这样：
    1. 节点面板可直接出现视频预览；
    2. 输出可不再只有 URL，而是提供一个本地 mp4/mov/webm 路径，方便后续节点或用户手动处理。
    """
    raw = str(video_url_or_path or "").strip()
    if not raw:
        return [], ""

    try:
        import folder_paths  # type: ignore
        output_dir = folder_paths.get_temp_directory()
        subfolder = ""
        media_type = "temp"
    except Exception:
        output_dir = os.path.join(MODULE_DIR, "banana_temp_previews")
        subfolder = ""
        media_type = "temp"

    os.makedirs(output_dir, exist_ok=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_\-]+", "_", str(label or "banana_video"))[:48] or "banana_video"
    ext = _guess_video_ext_from_value(raw, ".mp4")
    mime = _guess_video_mime_from_value(raw)
    filename = f"{safe_label}_{int(time.time() * 1000)}_{random.randint(1000, 9999)}{ext}"
    local_path = os.path.join(output_dir, filename)

    if os.path.isfile(raw):
        try:
            shutil.copyfile(raw, local_path)
        except Exception:
            local_path = raw
            filename = os.path.basename(raw)
    else:
        data = _download_binary(raw)
        with open(local_path, "wb") as f:
            f.write(data)

    item = {
        "filename": filename,
        "subfolder": subfolder,
        "type": media_type,
        "format": mime,
        "mime": mime,
        "source": local_path,
        "url": _comfyui_view_url(filename, media_type, subfolder),
        "view_url": _comfyui_view_url(filename, media_type, subfolder),
    }
    return [item], local_path



def _return_video_with_ui_preview(
    result_tuple: tuple,
    video_url_or_path,
    label: str = "banana_video",
) -> dict:
    """
    v8.2.3 修复：同 _return_images_with_ui_preview，必须返回
        {"ui": {...}, "result": (...)}
    否则视频节点执行后 ComfyUI 仍不认为任务完成，导致全局卡死。
    """
    ui_videos: list = []
    try:
        saved_videos, local_path = _save_video_for_comfyui_preview(
            video_url_or_path, label=label
        )
        if local_path:
            result_list = list(result_tuple)
            if len(result_list) == 1:
                result_list[0] = local_path
            elif len(result_list) >= 2:
                result_list[1] = local_path
            result_tuple = tuple(result_list)
        if saved_videos:
            ui_videos = saved_videos
            _publish_video_runtime_result(
                label=label,
                source=video_url_or_path,
                ui_videos=saved_videos,
                local_path=local_path,
            )
    except Exception as _e:
        logger.warning(
            f"[_return_video_with_ui_preview] 视频本地化/运行期记录失败，继续: {_e}"
        )
 
    return {"ui": {"videos": ui_videos}, "result": tuple(result_tuple)}

def _runtime_results_path() -> str:
    return os.path.join(MODULE_DIR, RUNTIME_RESULTS_FILE)


def _runtime_now_ms() -> int:
    return int(time.time() * 1000)


def _runtime_sort_value(item: Dict[str, Any]) -> float:
    try:
        value = item.get("updated_at_ms") or item.get("created_at_ms") or item.get("updated_at") or item.get("created_at") or 0
        if isinstance(value, str) and value.strip().isdigit():
            value = float(value.strip())
        if isinstance(value, (int, float)):
            value = float(value)
            return value if value > 10000000000 else value * 1000
    except Exception:
        pass
    return 0.0


def _runtime_sanitize_part(value: Any, fallback: str = "item") -> str:
    raw = str(value or fallback).strip()
    raw = re.sub(r"[^a-zA-Z0-9_\-\.]+", "_", raw)
    return raw[:80] or fallback


def _runtime_cache_output_root() -> str:
    candidates: List[str] = []
    try:
        import folder_paths  # type: ignore
        out = folder_paths.get_output_directory()
        if out:
            candidates.append(os.path.join(str(out), "hrio_design_runtime_cache"))
    except Exception:
        pass
    candidates.append(os.path.join(MODULE_DIR, "hrio_design_runtime_cache"))
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            continue
    return os.path.join(MODULE_DIR, "hrio_design_runtime_cache")


def _save_runtime_tensor_media(tensor: Any, group_key: Any, slot: str) -> Dict[str, Any]:
    """保存运行期结果到 output/hrio_design_runtime_cache，并返回 /view 引用。

    这里不再把大体积 base64 写进 JSON；设计师面板、最近生成和历史记录都只读轻量 URL。
    """
    if tensor is None:
        return {}
    try:
        root = _runtime_cache_output_root()
        safe_group = _runtime_sanitize_part(group_key, "runtime")
        safe_slot = _runtime_sanitize_part(slot, "image")
        run_dir = os.path.join(root, safe_group)
        os.makedirs(run_dir, exist_ok=True)
        path = os.path.join(run_dir, f"{safe_slot}.png")
        _save_tensor_image(tensor, path)
        ref = _comfyui_media_ref_from_path(path)
        if not ref:
            ref = {"path": path, "name": os.path.basename(path), "kind": "image"}
        ref.setdefault("slot", f"{safe_slot}.png")
        ref.setdefault("local_path", path)
        return ref
    except Exception as e:
        try:
            logger.warning(f"Hrio Design 运行期图片 JSON 缓存保存失败: {e}")
        except Exception:
            pass
        return {}


def _runtime_media_url(ref: Dict[str, Any]) -> str:
    if not isinstance(ref, dict):
        return ""
    return str(
        ref.get("url")
        or ref.get("view_url")
        or ref.get("public_url")
        or ref.get("publicUrl")
        or ref.get("oss_url")
        or ref.get("ossUrl")
        or ref.get("mp4url")
        or ""
    ).strip()


def _runtime_view_payload(
    *,
    view_key: str,
    label: str,
    status: str = "success",
    url: str = "",
    error: str = "",
    info: str = "",
    media_ref: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    failed = bool(error) or str(status).lower() in {"failed", "fail", "error"}
    missing = not failed and not str(url or "").strip()
    normalized_status = "failed" if failed else ("missing" if missing else (status or "success"))
    return {
        "view": view_key,
        "label": label,
        "status": normalized_status,
        "failed": failed,
        "placeholder": missing,
        "from_cache": False,
        "from_json_cache": True,
        "needs_regenerate": failed or missing,
        "seed": "",
        "attempt": "",
        "max_retry": "",
        "elapsed": 0.0,
        "info": info or error or ("JSON 缓存结果" if url else "暂无图片"),
        "error": error if failed else "",
        "image": url,
        "url": url,
        "view_url": url,
        "media": media_ref or {},
    }


def _runtime_alias_views(base_views: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = dict(base_views or {})
    alias_map = {
        "front": ("variant_a", "方案 A"),
        "side": ("variant_b", "方案 B"),
        "back": ("variant_c", "方案 C"),
    }
    for src, (alias, label) in alias_map.items():
        if src in out and alias not in out:
            item = dict(out[src])
            item["view"] = alias
            item["label"] = label
            out[alias] = item
    return out


def _history_item_to_runtime_group(item: Dict[str, Any]) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    node_type = str(item.get("node_type") or item.get("type") or "").strip()
    if node_type == "video":
        return None
    ok = item.get("ok") is not False
    err = "" if ok else str(item.get("error") or "未知错误")
    media_list = item.get("media") if isinstance(item.get("media"), list) else []
    by_slot: Dict[str, Dict[str, Any]] = {}
    for ref in media_list:
        if not isinstance(ref, dict):
            continue
        slot = str(ref.get("slot") or ref.get("filename") or ref.get("name") or "").strip()
        if slot:
            by_slot[slot] = ref
    def _first_ref(names: List[str]) -> Dict[str, Any]:
        for name in names:
            if by_slot.get(name):
                return by_slot[name]
        for ref in media_list:
            name = str((ref or {}).get("slot") or (ref or {}).get("filename") or (ref or {}).get("name") or "").lower()
            if any(name.endswith(x.lower()) for x in names):
                return ref
        return {}

    views: Dict[str, Dict[str, Any]] = {}
    if node_type == "normal_three_view":
        for view_key, label, names in [
            ("front", "正面图", ["front.png"]),
            ("side", "侧面图", ["side.png"]),
            ("back", "背面图", ["back.png"]),
        ]:
            ref = _first_ref(names)
            url = _runtime_media_url(ref)
            views[view_key] = _runtime_view_payload(
                view_key=view_key,
                label=label,
                status="success" if ok and url else ("failed" if err else "missing"),
                url=url,
                error=err,
                info="统一运行结果 JSON 缓存",
                media_ref=ref,
            )
        views = _runtime_alias_views(views)
        visible_variants = ["variant_a", "variant_b", "variant_c"]
    else:
        ref = _first_ref(["single.png", "single_image.png", "result.png", "front.png"])
        if not ref and item.get("local_image_path"):
            ref = _comfyui_media_ref_from_path(item.get("local_image_path"))
        url = _runtime_media_url(ref)
        front_payload = _runtime_view_payload(
            view_key="front",
            label="单图结果",
            status="success" if ok and url else ("failed" if err else "missing"),
            url=url,
            error=err,
            info="统一运行结果 JSON 缓存（单图）",
            media_ref=ref,
        )
        views["front"] = front_payload
        alias_payload = dict(front_payload)
        alias_payload["view"] = "variant_a"
        alias_payload["label"] = "单图结果"
        views["variant_a"] = alias_payload
        visible_variants = ["variant_a"]
    updated_ms = int(item.get("created_at_ms") or item.get("updated_at_ms") or _runtime_now_ms())
    key = str(item.get("run_id") or f"history:{node_type}:{item.get('sequence') or ''}:{updated_ms}")
    group = {
        "cache_key": key,
        "run_id": item.get("run_id") or key,
        "sequence": str(item.get("sequence") or ""),
        "from_history": True,
        "from_json_cache": True,
        "node_type": node_type or "normal_single_image",
        "mode_actual": str(item.get("mode_key") or item.get("template_key") or ""),
        "mode_key": str(item.get("mode_key") or item.get("template_key") or ""),
        "template_key": str(item.get("template_key") or item.get("mode_key") or ""),
        "template_display": str(item.get("labels") or item.get("template_display") or item.get("mode_display") or ("普通单图" if node_type != "normal_three_view" else "三方案并发")),
        "mode_display": str(item.get("labels") or item.get("template_display") or item.get("mode_display") or ""),
        "labels_prefix": str(item.get("labels") or ""),
        "output_strategy": "three_variants" if node_type == "normal_three_view" else "single_image",
        "visible_variants": visible_variants,
        "model": str(item.get("display_model") or item.get("model") or ""),
        "image_size": str(item.get("image_size") or ""),
        "aspect_ratio": str(item.get("aspect_ratio") or ""),
        "generate_scope": str(item.get("generate_scope") or "自动化"),
        "updated_at": updated_ms / 1000.0,
        "updated_at_ms": updated_ms,
        "created_at": item.get("created_at") or "",
        "created_at_ms": updated_ms,
        "has_error": (not ok) or any(bool(v.get("needs_regenerate")) for v in views.values()),
        "input_image_count": int(item.get("input_image_count") or 0),
        "uploaded_image_count": int(item.get("uploaded_image_count") or 0),
        "output_dir": str(item.get("output_dir") or ""),
        "source_images": item.get("source_images") or [],
        "views": views,
    }
    return group


def _history_item_to_runtime_video(item: Dict[str, Any]) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    node_type = str(item.get("node_type") or item.get("type") or "").strip()
    if node_type != "video" and not (item.get("mp4url") or item.get("local_video_path")):
        return None
    media_list = item.get("media") if isinstance(item.get("media"), list) else []
    ref = {}
    for m in media_list:
        if not isinstance(m, dict):
            continue
        kind = str(m.get("kind") or "").lower()
        slot = str(m.get("slot") or m.get("filename") or m.get("name") or "").lower()
        if kind == "video" or slot.endswith((".mp4", ".mov", ".webm", ".m4v")):
            ref = m
            break
    if not ref and item.get("local_video_path"):
        ref = _comfyui_media_ref_from_path(item.get("local_video_path"))
    url = _runtime_media_url(ref) or str(item.get("mp4url") or item.get("local_video_path") or "")
    if not url and item.get("ok") is not False:
        return None
    updated_ms = int(item.get("created_at_ms") or item.get("updated_at_ms") or _runtime_now_ms())
    key = str(item.get("run_id") or f"video:{item.get('sequence') or ''}:{updated_ms}")
    return {
        "key": key,
        "run_id": item.get("run_id") or key,
        "label": f"视频自动化 · 序号 {item.get('sequence') or '-'}",
        "sequence": str(item.get("sequence") or ""),
        "from_history": True,
        "from_json_cache": True,
        "updated_at": updated_ms / 1000.0,
        "updated_at_ms": updated_ms,
        "filename": str(ref.get("filename") or ref.get("name") or os.path.basename(str(item.get("local_video_path") or item.get("mp4url") or ""))),
        "subfolder": str(ref.get("subfolder") or ""),
        "type": str(ref.get("type") or "output"),
        "format": str(ref.get("format") or ref.get("mime") or _guess_video_mime_from_value(url)),
        "mime": str(ref.get("mime") or ref.get("format") or _guess_video_mime_from_value(url)),
        "view_url": url,
        "url": url,
        "source_url": str(item.get("mp4url") or ""),
        "local_path": str(item.get("local_video_path") or ""),
        "output_dir": str(item.get("output_dir") or ""),
        "model": str(item.get("display_model") or item.get("model") or ""),
        "has_error": item.get("ok") is False,
        "error": str(item.get("error") or ""),
    }


def _read_runtime_results_file() -> Dict[str, Any]:
    path = _runtime_results_path()
    if not os.path.exists(path):
        return {"ok": True, "version": "8.2.3", "updated_at_ms": 0, "count": 0, "video_count": 0, "groups": [], "videos": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"ok": True, "version": "8.2.3", "updated_at_ms": 0, "count": 0, "video_count": 0, "groups": [], "videos": []}
    if not isinstance(data, dict):
        data = {}
    groups = data.get("groups") if isinstance(data.get("groups"), list) else []
    videos = data.get("videos") if isinstance(data.get("videos"), list) else []
    return {
        "ok": True,
        "version": str(data.get("version") or "8.2.2"),
        "latest_key": str(data.get("latest_key") or ""),
        "latest_video_key": str(data.get("latest_video_key") or ""),
        "updated_at_ms": int(data.get("updated_at_ms") or 0),
        "count": len(groups),
        "video_count": len(videos),
        "groups": groups[-_RUNTIME_RESULTS_MAX_GROUPS:],
        "videos": videos[-_RUNTIME_RESULTS_MAX_VIDEOS:],
    }


def _write_runtime_results_file(payload: Dict[str, Any]) -> None:
    path = _runtime_results_path()
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _dedupe_runtime_items(items: List[Dict[str, Any]], key_names: Tuple[str, ...], limit: int) -> List[Dict[str, Any]]:
    """
    去重 + 影子记录合并。

    规则：
    1. 主键去重（cache_key / run_id / key）。
    2. 影子记录去重：同 sequence + 同 node_type + 10 分钟内，
       如果已存在带 output_dir 的完整记录，则丢弃没有 output_dir 的快速记录。
       避免 _publish_runtime_result 和 _append_automation_history_record 各写一条
       导致历史面板出现两条相同序号的结果。
    """
    # 先按时间降序排列
    sorted_items = sorted(
        [x for x in items if isinstance(x, dict)],
        key=_runtime_sort_value,
        reverse=True,
    )

    # 第一轮：主键去重，保留时间最新的
    primary_seen: set = set()
    primary_out: List[Dict[str, Any]] = []
    for item in sorted_items:
        key = ""
        for name in key_names:
            if item.get(name):
                key = str(item.get(name))
                break
        if not key:
            key = json.dumps({"t": _runtime_sort_value(item), "n": len(primary_out)}, ensure_ascii=False)
        if key in primary_seen:
            continue
        primary_seen.add(key)
        primary_out.append(item)

    # 第二轮：影子记录去重
    # 同 sequence + 同 node_type + 10 分钟内 → 优先保留有 output_dir 的完整记录
    _10_MIN_MS = 10 * 60 * 1000
    shadow_out: List[Dict[str, Any]] = []
    # 记录已确认保留的 (sequence, node_type) 完整记录的时间戳
    confirmed: Dict[tuple, float] = {}  # (seq, node_type) -> max_ts_ms (有 output_dir 的)

    # 先扫一遍，记录所有有 output_dir 的完整记录
    for item in primary_out:
        seq = str(item.get("sequence") or "").strip()
        nt = str(item.get("node_type") or "").strip()
        out_dir = str(item.get("output_dir") or "").strip()
        ts = _runtime_sort_value(item)
        if seq and nt and out_dir:
            k = (seq, nt)
            if k not in confirmed or ts > confirmed[k]:
                confirmed[k] = ts

    # 再过滤：丢弃"影子记录"（同 seq+nt、时间接近、无 output_dir）
    for item in primary_out:
        seq = str(item.get("sequence") or "").strip()
        nt = str(item.get("node_type") or "").strip()
        out_dir = str(item.get("output_dir") or "").strip()
        ts = _runtime_sort_value(item)

        if seq and nt and not out_dir:
            k = (seq, nt)
            if k in confirmed and abs(confirmed[k] - ts) <= _10_MIN_MS:
                # 这是影子快速记录，丢弃
                continue

        shadow_out.append(item)
        if len(shadow_out) >= limit:
            break

    return shadow_out

def _runtime_file_upsert(groups: List[Dict[str, Any]] | None = None, videos: List[Dict[str, Any]] | None = None) -> None:
    try:
        with _RUNTIME_RESULTS_LOCK:
            current = _read_runtime_results_file()
            merged_groups = _dedupe_runtime_items(list(groups or []) + list(current.get("groups") or []), ("cache_key", "run_id"), _RUNTIME_RESULTS_MAX_GROUPS)
            merged_videos = _dedupe_runtime_items(list(videos or []) + list(current.get("videos") or []), ("key", "run_id"), _RUNTIME_RESULTS_MAX_VIDEOS)
            payload = {
                "ok": True,
                "version": "8.2.3",
                "updated_at_ms": _runtime_now_ms(),
                "latest_key": str((merged_groups[0] or {}).get("cache_key") or "") if merged_groups else "",
                "latest_video_key": str((merged_videos[0] or {}).get("key") or "") if merged_videos else "",
                "count": len(merged_groups),
                "video_count": len(merged_videos),
                "groups": merged_groups,
                "videos": merged_videos,
            }
            _write_runtime_results_file(payload)
    except Exception as e:
        try:
            logger.warning(f"Hrio Design 运行期 JSON 缓存写入失败: {e}")
        except Exception:
            pass


def _history_payload_as_runtime() -> Dict[str, Any]:
    try:
        data = _read_automation_history_file()
    except Exception:
        data = {"items": []}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    groups: List[Dict[str, Any]] = []
    videos: List[Dict[str, Any]] = []
    for item in items:
        g = _history_item_to_runtime_group(item)
        if g:
            groups.append(g)
        v = _history_item_to_runtime_video(item)
        if v:
            videos.append(v)
    groups = _dedupe_runtime_items(groups, ("cache_key", "run_id"), _RUNTIME_RESULTS_MAX_GROUPS)
    videos = _dedupe_runtime_items(videos, ("key", "run_id"), _RUNTIME_RESULTS_MAX_VIDEOS)
    return {"groups": groups, "videos": videos}


def _runtime_memory_payload() -> Dict[str, Any]:
    groups = sorted(
        _LAST_THREE_VIEW_RUNTIME.values(),
        key=lambda x: float(x.get("updated_at") or 0),
        reverse=True,
    )
    videos = sorted(
        _LAST_VIDEO_RUNTIME.values(),
        key=lambda x: float(x.get("updated_at") or 0),
        reverse=True,
    )
    return {
        "groups": groups,
        "videos": videos,
        "latest_key": _LAST_THREE_VIEW_LATEST_KEY,
        "latest_video_key": _LAST_VIDEO_LATEST_KEY,
    }

def _publish_runtime_result(
    *,
    cache_key: Any,
    labels_prefix: str,
    model: str,
    image_size: str,
    aspect_ratio: str,
    generate_scope: str,
    results_by_key: Dict[str, Dict[str, Any]],
    errors_by_key: Dict[str, str],
) -> None:
    global _LAST_THREE_VIEW_LATEST_KEY

    key = _cache_key_or_default(cache_key)
    now = time.time()
    views: Dict[str, Any] = {}

    for view_key, label in _THREE_VIEW_ORDER:
        item = results_by_key.get(view_key) or {}
        failed = bool(item.get("failed"))
        placeholder = bool(item.get("placeholder"))
        from_cache = bool(item.get("from_cache"))
        status = "success"
        if failed:
            status = "failed"
        elif placeholder:
            status = "missing"
        elif from_cache:
            status = "cached"

        media_ref = _save_runtime_tensor_media(item.get("tensor"), key, view_key) if item.get("tensor") is not None else {}
        image_url = _runtime_media_url(media_ref)

        view_payload = {
            "view": view_key,
            "label": label,
            "status": status,
            "failed": failed,
            "placeholder": placeholder,
            "from_cache": from_cache,
            "needs_regenerate": failed or placeholder,
            "seed": str(item.get("seed", "")),
            "attempt": str(item.get("attempt", "")),
            "max_retry": str(item.get("max_retry", "")),
            "elapsed": float(item.get("elapsed") or 0),
            "info": str(item.get("info") or ""),
            "error": str(errors_by_key.get(view_key) or (item.get("info") if failed else "") or ""),
            "image": "",
            "url": "",
            "view_url": "",
            "media": media_ref,
        }
        view_payload["image"] = image_url or (_tensor_to_preview_data_url(item.get("tensor")) if item.get("tensor") is not None else "")
        view_payload["url"] = image_url
        view_payload["view_url"] = image_url
        view_payload["from_json_cache"] = bool(image_url)
        views[view_key] = view_payload

        # 设计师新版前端按 variant_a / variant_b / variant_c 读取结果；
        # 旧三视图仍按 front / side / back 读取。这里双写，避免两套面板互相不兼容。
        alias_map = {"front": ("variant_a", "方案 A"), "side": ("variant_b", "方案 B"), "back": ("variant_c", "方案 C")}
        if view_key in alias_map:
            alias_key, alias_label = alias_map[view_key]
            alias_payload = dict(view_payload)
            alias_payload["view"] = alias_key
            alias_payload["label"] = alias_label
            views[alias_key] = alias_payload

    mode_actual = ""
    try:
        if str(key).startswith("banana_image_generation:"):
            mode_actual = str(key).split(":")[-1]
    except Exception:
        mode_actual = ""

    _LAST_THREE_VIEW_RUNTIME[key] = {
        "cache_key": key,
        "run_id": key,
        "node_type": "normal_three_view",
        "output_strategy": "three_variants",
        "visible_variants": ["variant_a", "variant_b", "variant_c"],
        "mode_actual": mode_actual,
        "mode_key": mode_actual,
        "template_key": mode_actual,
        "template_display": labels_prefix.strip("- ") if isinstance(labels_prefix, str) else "",
        "mode_display": labels_prefix.strip("- ") if isinstance(labels_prefix, str) else "",
        "labels_prefix": labels_prefix,
        "model": model,
        "image_size": image_size,
        "aspect_ratio": aspect_ratio,
        "generate_scope": generate_scope,
        "updated_at": now,
        "updated_at_ms": int(now * 1000),
        "has_error": any(v.get("needs_regenerate") for k, v in views.items() if str(k).startswith("variant_")),
        "views": views,
    }
    _LAST_THREE_VIEW_LATEST_KEY = key
    _runtime_file_upsert(groups=[_LAST_THREE_VIEW_RUNTIME[key]])


def _publish_single_image_runtime_result(
    *,
    cache_key: Any,
    label: str,
    model: str,
    image_size: str,
    aspect_ratio: str,
    tensor: torch.Tensor | None = None,
    error: str = "",
    duplicate_to_all_variants: bool = False,
) -> None:
    """
    将普通单图节点的结果同步到设计师面板的 /runtime。
    设计师面板的“最近生成”按三方案结构读取，所以这里把单图结果映射到
    front / variant_a，并按需补齐其余视图，保证可以直接预览。
    """
    global _LAST_THREE_VIEW_LATEST_KEY

    key = _cache_key_or_default(cache_key)
    now = time.time()

    image_data = ""
    media_ref: Dict[str, Any] = {}
    if tensor is not None:
        media_ref = _save_runtime_tensor_media(tensor, key, "single")
        image_data = _runtime_media_url(media_ref)
        if not image_data:
            try:
                image_data = _tensor_to_preview_data_url(tensor)
            except Exception:
                image_data = ""

    normalized_error = str(error or "").strip()
    base_status = "success"
    if normalized_error:
        base_status = "failed"
    elif not image_data:
        base_status = "missing"

    def _view_payload(view_key: str, display_label: str, use_image: bool) -> Dict[str, Any]:
        has_image = bool(use_image and image_data)
        status = base_status if has_image or normalized_error else "missing"
        failed = bool(normalized_error)
        return {
            "view": view_key,
            "label": display_label,
            "status": status,
            "failed": failed,
            "placeholder": not has_image,
            "from_cache": False,
            "needs_regenerate": failed or not has_image,
            "seed": "",
            "attempt": "",
            "max_retry": "",
            "elapsed": 0.0,
            "info": normalized_error if failed else ("普通单图结果" if has_image else "暂无图片"),
            "error": normalized_error if failed else "",
            "image": image_data if has_image else "",
            "url": image_data if has_image else "",
            "view_url": image_data if has_image else "",
            "media": media_ref if has_image else {},
            "from_json_cache": bool(has_image and image_data and not str(image_data).startswith("data:")),
        }

    views: Dict[str, Any] = {}
    front_payload = _view_payload("front", "单图结果", True)
    views["front"] = front_payload
    alias_payload = dict(front_payload)
    alias_payload["view"] = "variant_a"
    alias_payload["label"] = "单图结果"
    views["variant_a"] = alias_payload

    _LAST_THREE_VIEW_RUNTIME[key] = {
        "cache_key": key,
        "run_id": key,
        "mode_actual": "",
        "mode_key": "",
        "template_key": "",
        "template_display": str(label or "普通单图"),
        "mode_display": str(label or "普通单图"),
        "labels_prefix": str(label or "普通单图"),
        "output_strategy": "single_image",
        "visible_variants": ["variant_a"],
        "node_type": "normal_single_image",
        "model": model,
        "image_size": image_size,
        "aspect_ratio": aspect_ratio,
        "generate_scope": "单图",
        "updated_at": now,
        "updated_at_ms": int(now * 1000),
        "has_error": any(bool(v.get("needs_regenerate")) for k, v in views.items() if str(k).startswith("variant_") or k == "front"),
        "views": views,
    }
    _LAST_THREE_VIEW_LATEST_KEY = key
    _runtime_file_upsert(groups=[_LAST_THREE_VIEW_RUNTIME[key]])


def _runtime_results_payload() -> Dict[str, Any]:
    mem = _runtime_memory_payload()
    file_payload = _read_runtime_results_file()

    # 如果历史版本尚未生成 banana_runtime_results.json，则从 automation history 兜底构建一次；
    # 一旦用户点击“清空预览”，会写入空 runtime JSON，不再自动把全部历史塞回“最近生成”。
    if not os.path.exists(_runtime_results_path()):
        history_payload = _history_payload_as_runtime()
    else:
        history_payload = {"groups": [], "videos": []}

    groups = _dedupe_runtime_items(
        list(mem.get("groups") or []) + list(file_payload.get("groups") or []) + list(history_payload.get("groups") or []),
        ("cache_key", "run_id"),
        _RUNTIME_RESULTS_MAX_GROUPS,
    )
    videos = _dedupe_runtime_items(
        list(mem.get("videos") or []) + list(file_payload.get("videos") or []) + list(history_payload.get("videos") or []),
        ("key", "run_id"),
        _RUNTIME_RESULTS_MAX_VIDEOS,
    )

    latest_key = str(mem.get("latest_key") or file_payload.get("latest_key") or ((groups[0] or {}).get("cache_key") if groups else "") or "")
    latest_video_key = str(mem.get("latest_video_key") or file_payload.get("latest_video_key") or ((videos[0] or {}).get("key") if videos else "") or "")
    return {
        "ok": True,
        "version": "8.2.3",
        "updated_at_ms": _runtime_now_ms(),
        "latest_key": latest_key,
        "latest_video_key": latest_video_key,
        "count": len(groups),
        "video_count": len(videos),
        "groups": groups,
        "videos": videos,
        "latest": groups[0] if groups else {},
    }


def _clear_runtime_results() -> Dict[str, Any]:
    global _LAST_THREE_VIEW_LATEST_KEY, _LAST_VIDEO_LATEST_KEY
    _LAST_THREE_VIEW_RUNTIME.clear()
    _LAST_THREE_VIEW_LATEST_KEY = ""
    _LAST_VIDEO_RUNTIME.clear()
    _LAST_VIDEO_LATEST_KEY = ""
    empty = {
        "ok": True,
        "version": "8.2.3",
        "updated_at_ms": _runtime_now_ms(),
        "latest_key": "",
        "latest_video_key": "",
        "count": 0,
        "video_count": 0,
        "groups": [],
        "videos": [],
    }
    try:
        with _RUNTIME_RESULTS_LOCK:
            _write_runtime_results_file(empty)
    except Exception as e:
        logger.warning(f"清空运行期 JSON 缓存失败: {e}")
    return {"ok": True, "message": "已清空 Hrio Design 运行期预览缓存；历史记录不会被删除"}


def _comfyui_view_url(filename: Any, media_type: str = "temp", subfolder: str = "") -> str:
    filename = str(filename or "").strip()
    if not filename:
        return ""
    try:
        from urllib.parse import urlencode
        return "/view?" + urlencode({
            "filename": filename,
            "type": str(media_type or "temp"),
            "subfolder": str(subfolder or ""),
        })
    except Exception:
        return f"/view?filename={filename}&type={media_type or 'temp'}&subfolder={subfolder or ''}"


def _publish_video_runtime_result(
    *,
    label: str,
    source: Any = "",
    ui_videos: List[Dict[str, Any]] | None = None,
    local_path: str = "",
) -> None:
    global _LAST_VIDEO_LATEST_KEY

    try:
        videos = list(ui_videos or [])
        if not videos and not local_path and not source:
            return

        now = time.time()
        key = f"video:{int(now * 1000)}:{random.randint(1000, 9999)}"
        first = videos[0] if videos else {}
        filename = str(first.get("filename") or os.path.basename(str(local_path or source or ""))).strip()
        subfolder = str(first.get("subfolder") or "")
        media_type = str(first.get("type") or "temp")
        view_url = str(first.get("url") or first.get("view_url") or _comfyui_view_url(filename, media_type, subfolder))

        _LAST_VIDEO_RUNTIME[key] = {
            "key": key,
            "label": str(label or "Hrio Design 视频"),
            "updated_at": now,
            "updated_at_ms": int(now * 1000),
            "filename": filename,
            "subfolder": subfolder,
            "type": media_type,
            "format": str(first.get("format") or first.get("mime") or _guess_video_mime_from_value(filename or source)),
            "mime": str(first.get("mime") or first.get("format") or _guess_video_mime_from_value(filename or source)),
            "view_url": view_url,
            "url": view_url,
            "source_url": str(source or ""),
            "local_path": str(local_path or ""),
        }
        _LAST_VIDEO_LATEST_KEY = key
        _runtime_file_upsert(videos=[_LAST_VIDEO_RUNTIME[key]])

        # 只保留最近 60 条，避免长时间运行导致内存膨胀。
        if len(_LAST_VIDEO_RUNTIME) > 60:
            old_keys = sorted(
                _LAST_VIDEO_RUNTIME.keys(),
                key=lambda k: float((_LAST_VIDEO_RUNTIME.get(k) or {}).get("updated_at") or 0),
            )
            for old_key in old_keys[: max(0, len(_LAST_VIDEO_RUNTIME) - 60)]:
                _LAST_VIDEO_RUNTIME.pop(old_key, None)
    except Exception as e:
        logger.warning(f"Hrio Design 视频运行期缓存写入失败: {e}")


def _coerce_json_object(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def _extract_automation_payload_from_workflow(extra_pnginfo: Any, unique_id: Any) -> str:
    uid = str(unique_id or "").strip()
    if not uid:
        return ""

    data = _coerce_json_object(extra_pnginfo)
    workflow = data.get("workflow") if isinstance(data, dict) else {}
    workflow = _coerce_json_object(workflow)
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else []

    if not isinstance(nodes, list):
        return ""

    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get("id") or "").strip() != uid:
            continue

        props = node.get("properties") or {}
        if isinstance(props, dict):
            for key in (
                "hrio_design_automation_payload",
                "automation_payload",
                "自动化映射",
                "banana_automation_payload",
            ):
                value = props.get(key)
                if value is None:
                    continue
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)
                text = str(value or "").strip()
                if text:
                    return text

        # 兼容极少数旧工作流：automation_payload 仍保存在 widgets_values 里。
        for value in node.get("widgets_values") or []:
            if isinstance(value, str) and "input_roots" in value and "enabled" in value:
                return value

    return ""


def _extract_automation_payload_from_prompt(prompt_graph: Any, unique_id: Any) -> str:
    uid = str(unique_id or "").strip()
    data = _coerce_json_object(prompt_graph)
    if not uid or not isinstance(data, dict):
        return ""

    node = data.get(uid) or data.get(int(uid)) if uid.isdigit() else data.get(uid)
    if not isinstance(node, dict):
        return ""

    for bucket_name in ("inputs", "properties"):
        bucket = node.get(bucket_name) or {}
        if not isinstance(bucket, dict):
            continue
        for key in ("hrio_design_automation_payload", "banana_automation_payload", "automation_payload", "自动化映射"):
            value = bucket.get(key)
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _resolve_automation_payload(
    automation_payload: Any = "",
    *,
    unique_id: Any = None,
    prompt: Any = None,
    extra_pnginfo: Any = None,
    values: Dict[str, Any] | None = None,
) -> str:
    """
    统一恢复自动化 JSON。

    前端会把 automation_payload 写到 widget、node.properties、PROMPT inputs/properties
    和 EXTRA_PNGINFO workflow。这里全部兜底读取，避免“已经应用自动化，但队列运行时节点拿不到 JSON”。
    """
    text = str(automation_payload or "").strip()
    if text:
        return text

    values = values if isinstance(values, dict) else {}
    for key in (
        "automation_payload",
        "hrio_design_automation_payload",
        "banana_automation_payload",
        "自动化映射",
        "automation",
        "payload",
    ):
        value = values.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        text = str(value or "").strip()
        if text:
            return text

    text = _extract_automation_payload_from_prompt(prompt, unique_id)
    if text:
        return text

    text = _extract_automation_payload_from_workflow(extra_pnginfo, unique_id)
    if text:
        return text

    return ""


def _automation_payload_widget() -> Tuple[str, Dict[str, Any]]:
    """
    给所有 Hrio 节点保留一个可序列化的自动化 JSON 入口。

    注意：这里不能放到 hidden 里，因为 ComfyUI 的 hidden 主要用于 UNIQUE_ID / PROMPT / EXTRA_PNGINFO。
    前端会把这个 widget 默认折叠/隐藏，只保留后台序列化和执行时读取能力。
    """
    return (
        "STRING",
        {
            "default": "",
            "multiline": True,
            "tooltip": "自动化 JSON。前端默认隐藏，只在点击节点上的自动化折叠按钮后显示；后台仍会序列化并参与运行。",
        },
    )


def _compose_single_image_prompt(prompt: str, negative_prompt: str = "") -> str:
    """普通单图只使用 prompt 本身；negative_prompt 仅保留给旧工作流反序列化，不再参与请求。"""
    final_prompt = str(prompt or "").strip()
    final_prompt += "\n\n输出要求：只输出一张完整图片，不要拼图，不要多视图排版，不要文字标注，不要水印。"
    return final_prompt

def _node_base_values(
    api_key: str,
    prompt: str,
    model: str,
    image_size: str,
    aspect_ratio: str,
    enable_oss: bool | None = None,
    auto_retry_until_success: bool = True,
    max_retry_per_view: int = 8,
    retry_interval_sec: float = 1.5,
) -> Dict[str, Any]:
    values = {
        "api_key": str(api_key or "").strip(),
        "prompt": str(prompt or ""),
        "model": model,
        "image_size": image_size,
        "aspect_ratio": aspect_ratio,
        "auto_retry_until_success": bool(auto_retry_until_success),
        "max_retry_per_view": int(max_retry_per_view),
        "retry_interval_sec": float(retry_interval_sec),
    }

    if enable_oss is not None:
        values["enable_oss"] = bool(enable_oss)

    return values

def _resolve_enable_oss(values: Dict[str, Any]) -> bool:
    if "enable_oss" in values:
        return _value_as_bool(values.get("enable_oss"), _cfg_bool("enable_oss", True))

    return _cfg_bool("enable_oss", True)


def _resolve_compress_images(values: Dict[str, Any]) -> bool:
    if "compress_images" in values:
        return _value_as_bool(values.get("compress_images"), _cfg_bool("compress_images", True))

    return _cfg_bool("compress_images", True)


def _resolve_force_hd(values: Dict[str, Any]) -> bool:
    if "force_hd" in values:
        return _value_as_bool(values.get("force_hd"), _cfg_bool("force_hd", True))

    return _cfg_bool("force_hd", True)


def _build_body_from_values(values: Dict[str, Any], image_urls: List[str], seed: int) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    api_key = str(values.get("api_key") or "").strip()
    prompt = str(values.get("prompt") or "")

    model_display = str(values.get("model") or _manual_model_default()).strip()
    actual_model = _MODEL_DISPLAY_TO_ACTUAL.get(model_display, model_display)

    image_size_display = str(values.get("image_size") or _manual_image_size_default()).strip()
    image_size_actual = _enum_actual("image_size_options", image_size_display)

    if image_size_actual:
        image_size_actual = str(image_size_actual).strip().lower()

    aspect_display = str(values.get("aspect_ratio") or _manual_aspect_ratio_default("Auto")).strip()
    aspect_actual = _enum_actual("aspect_ratio_options", aspect_display)

    enable_oss = _resolve_enable_oss(values)
    compress_images = _resolve_compress_images(values)
    force_hd = _resolve_force_hd(values)

    parts: List[Dict[str, Any]] = []

    for u in image_urls:
        u = str(u or "").strip()

        if u:
            parts.append({
                "fileData": {
                    "mimeType": _guess_mime_from_url(u, "image/png"),
                    "fileUri": u,
                }
            })

    parts.append({"text": prompt})

    body: Dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": parts,
            }
        ],
        "generationConfig": {
            "topP": 0.95,
            "seed": seed,
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {},
        },
        "stream": False,
        "enable_oss": enable_oss,
        "compress_images": compress_images,
        "force_hd": force_hd,
    }

    if image_size_actual:
        body["generationConfig"]["imageConfig"]["imageSize"] = image_size_actual

    if aspect_actual:
        body["generationConfig"]["imageConfig"]["aspectRatio"] = str(aspect_actual).strip()

    meta = {
        "api_key": api_key,
        "display_model": model_display,
        "actual_model": actual_model,
        "prompt": prompt,
        "image_size": image_size_actual,
        "aspect_ratio": aspect_actual,
        "enable_oss": enable_oss,
        "compress_images": compress_images,
        "force_hd": force_hd,
    }

    return actual_model, body, meta


def _send(api_key: str, body: Dict[str, Any], model: str, enable_oss: bool = False) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }

    _, data, _, _ = _request_json_with_failover(
        "POST",
        _gemini_url,
        builder_args=(model,),
        builder_kwargs={"enable_oss": enable_oss},
        headers=headers,
        json_payload=body,
        timeout=_cfg_int("read_timeout_sec", _TIMEOUT_IMAGE),
        action_name=f"AI 生成 {model}",
    )

    return data


def _extract_urls_from_text(text: str) -> List[str]:
    if not text:
        return []

    return [m.group(0).rstrip(").,，。]】\"'") for m in _MEDIA_URL_RE.finditer(str(text))]


def _walk_extract_media(obj: Any, urls: List[str], inline_items: List[Tuple[str, str]], texts: List[str]) -> None:
    if obj is None:
        return

    if isinstance(obj, dict):
        inline = obj.get("inlineData") or obj.get("inline_data")

        if isinstance(inline, dict):
            data = inline.get("data")
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"

            if isinstance(data, str) and data.strip():
                inline_items.append((str(mime), data.strip()))

        file_data = obj.get("fileData") or obj.get("file_data")

        if isinstance(file_data, dict):
            uri = file_data.get("fileUri") or file_data.get("uri") or file_data.get("url")

            if isinstance(uri, str) and uri.strip():
                urls.append(uri.strip())

        for key in ("url", "uri", "downloadUrl", "download_url", "oss_url", "ossUrl", "fileUri", "public_url"):
            value = obj.get(key)

            if isinstance(value, str) and value.strip():
                urls.append(value.strip())

        text = obj.get("text")

        if isinstance(text, str) and text.strip():
            texts.append(text)
            urls.extend(_extract_urls_from_text(text))

        for v in obj.values():
            _walk_extract_media(v, urls, inline_items, texts)

    elif isinstance(obj, list):
        for item in obj:
            _walk_extract_media(item, urls, inline_items, texts)

    elif isinstance(obj, str):
        urls.extend(_extract_urls_from_text(obj))


def _extract_media_from_gemini_response(data: Dict[str, Any]) -> Tuple[List[torch.Tensor], List[str]]:
    urls: List[str] = []
    inline_items: List[Tuple[str, str]] = []
    texts: List[str] = []

    _walk_extract_media(data, urls, inline_items, texts)

    tensors: List[torch.Tensor] = []
    info_lines: List[str] = []

    seen_urls = set()

    for url in urls:
        url = str(url or "").strip()

        if not url or url in seen_urls:
            continue

        seen_urls.add(url)

        try:
            img = _download_image(url)
            tensors.append(_pil_to_tensor(img))
            info_lines.append(f"image_url: {url}")
        except Exception as e:
            logger.warning(f"图片 URL 下载失败，跳过: {url} | {e}")

    for mime, b64 in inline_items:
        try:
            raw = base64.b64decode(b64)
            img = Image.open(BytesIO(raw)).convert("RGB")
            tensors.append(_pil_to_tensor(img))
            info_lines.append(f"inline_image: {mime}, bytes={len(raw)}")
        except Exception as e:
            logger.warning(f"inlineData 图片解析失败，跳过: {e}")

    for text in texts:
        s = str(text or "").strip()

        if s:
            info_lines.append(f"text: {s[:1000]}")

    return tensors, info_lines


def _single_image_generation_job(label: str, values: Dict[str, Any], image_urls: List[str]) -> Dict[str, Any]:
    auto_retry, max_retry, retry_interval = _resolve_retry_options(values)
    attempt = 0
    first_start = time.time()

    while True:
        attempt += 1
        job_start = time.time()
        seed = random.randint(0, 999_999_999)

        try:
            actual_model, body, meta = _build_body_from_values(values, image_urls, seed)

            if actual_model == "veo3.1":
                raise RuntimeError("三方案节点只支持图片模型，请选择 banano2 / banano-pro / gemini3.1-pro")

            resolved_key = str(meta.get("api_key") or "").strip() or _cfg("api_key", "")
            if not resolved_key:
                raise RuntimeError("请在节点中填入 API Key")

            logger.info(
                f"[{label}] 第 {attempt}/{max_retry} 次请求: model={actual_model}, size={meta.get('image_size')}, "
                f"ratio={meta.get('aspect_ratio')}, seed={seed}, ref_image_count={len(image_urls)}"
            )

            resp_data = _send(resolved_key, body, actual_model, enable_oss=bool(meta.get("enable_oss")))
            result_tensors, info_lines = _extract_media_from_gemini_response(resp_data)

            if not result_tensors:
                raw_resp = json.dumps(resp_data, ensure_ascii=False)[:2500]
                raise RuntimeError(f"后端未返回可解析图片；响应内容: {raw_resp}")

            elapsed = time.time() - job_start
            total_elapsed = time.time() - first_start
            image_out = result_tensors[0]
            if image_out.ndim == 3:
                image_out = image_out.unsqueeze(0)

            if attempt > 1:
                info_lines.append(f"auto_retry_success: 第 {attempt}/{max_retry} 次重试成功，累计耗时 {total_elapsed:.1f}s")

            return {
                "label": label,
                "tensor": image_out,
                "elapsed": elapsed,
                "total_elapsed": total_elapsed,
                "model": actual_model,
                "display_model": meta.get("display_model"),
                "image_size": meta.get("image_size"),
                "aspect_ratio": meta.get("aspect_ratio"),
                "seed": seed,
                "attempt": attempt,
                "max_retry": max_retry,
                "auto_retry": auto_retry,
                "info": "\n".join(info_lines),
            }

        except Exception as e:
            last_error = str(e)[:2200]
            logger.warning(f"[{label}] 第 {attempt}/{max_retry} 次失败: {last_error}")
            if attempt >= max_retry:
                raise RuntimeError(f"[{label}] 自动重试 {attempt}/{max_retry} 次后仍失败: {last_error}") from e
            time.sleep(retry_interval)

def _run_three_view_jobs(
    *,
    api_key: str,
    model: str,
    image_size: str,
    aspect_ratio: str,
    image_urls: List[str],
    prompts: Dict[str, str],
    labels_prefix: str = "",
    generate_scope: str = "全部并发生成",
    cache_key: Any = None,
    auto_retry_until_success: bool = True,
    max_retry_per_view: int = 8,
    retry_interval_sec: float = 1.5,
) -> Dict[str, Any]:
    """
    三方案并发调度：
    1. 三个视图互不影响：任意一路失败，只在对应输出口返回错误图，其他成功图正常返回。
    2. 支持单独重抽：仅重新生成正面/侧面/背面时，其他视图使用本次 ComfyUI 运行期内的上一次成功缓存。
    3. cache_key 建议使用 unique_id 拼出，保证不同节点之间缓存隔离。
    """
    scope = _normalize_generate_scope(generate_scope)
    active_keys = set(_THREE_VIEW_SCOPE_MAP[scope])

    jobs: List[Tuple[str, str, Dict[str, Any]]] = [
        ("front", "正面图", _node_base_values(api_key, prompts.get("front", ""), model, image_size, aspect_ratio, auto_retry_until_success=auto_retry_until_success, max_retry_per_view=max_retry_per_view, retry_interval_sec=retry_interval_sec)),
        ("side", "侧面图", _node_base_values(api_key, prompts.get("side", ""), model, image_size, aspect_ratio, auto_retry_until_success=auto_retry_until_success, max_retry_per_view=max_retry_per_view, retry_interval_sec=retry_interval_sec)),
        ("back", "背面图", _node_base_values(api_key, prompts.get("back", ""), model, image_size, aspect_ratio, auto_retry_until_success=auto_retry_until_success, max_retry_per_view=max_retry_per_view, retry_interval_sec=retry_interval_sec)),
    ]

    results_by_key: Dict[str, Dict[str, Any]] = {}
    errors_by_key: Dict[str, str] = {}

    active_jobs = [(key, label, values) for key, label, values in jobs if key in active_keys]

    if active_jobs:
        with ThreadPoolExecutor(max_workers=max(1, len(active_jobs))) as executor:
            future_map = {
                executor.submit(
                    _single_image_generation_job,
                    f"{labels_prefix}{label}",
                    values,
                    image_urls,
                ): (key, label)
                for key, label, values in active_jobs
            }

            for future in as_completed(future_map):
                key, label = future_map[future]

                try:
                    item = future.result()
                    results_by_key[key] = item

                    if item.get("tensor") is not None:
                        _set_cached_view(cache_key, key, item["tensor"])

                except Exception as e:
                    msg = str(e)[:1800]
                    errors_by_key[key] = msg

                    logger.error(f"[{labels_prefix}{label}] 单路生成失败，但不影响其他视图: {msg}")

                    failed_tensor = _error_img(f"{label} 生成失败：{msg[:220]}")
                    results_by_key[key] = {
                        "label": f"{labels_prefix}{label}",
                        "tensor": failed_tensor,
                        "elapsed": 0.0,
                        "model": model,
                        "display_model": model,
                        "image_size": image_size,
                        "aspect_ratio": aspect_ratio,
                        "seed": "",
                        "info": f"{label} 生成失败：{msg}",
                        "failed": True,
                    }

    for key, label, _values in jobs:
        if key in results_by_key:
            continue

        cached = _get_cached_view(cache_key, key)

        if cached is not None:
            results_by_key[key] = {
                "label": f"{labels_prefix}{label}",
                "tensor": cached,
                "elapsed": 0.0,
                "model": model,
                "display_model": model,
                "image_size": image_size,
                "aspect_ratio": aspect_ratio,
                "seed": "",
                "info": f"{label} 使用上一次成功缓存结果",
                "from_cache": True,
            }
        else:
            placeholder = _error_img(f"{label} 未重新生成，且当前节点暂无缓存。请先执行一次【全部并发生成】。")
            results_by_key[key] = {
                "label": f"{labels_prefix}{label}",
                "tensor": placeholder,
                "elapsed": 0.0,
                "model": model,
                "display_model": model,
                "image_size": image_size,
                "aspect_ratio": aspect_ratio,
                "seed": "",
                "info": f"{label} 无缓存。请先执行一次【全部并发生成】。",
                "from_cache": False,
                "placeholder": True,
            }

    ordered = [results_by_key[k] for k, _label in _THREE_VIEW_ORDER]

    front = _first_image_or_error([results_by_key["front"]["tensor"]], "正面图")
    side = _first_image_or_error([results_by_key["side"]["tensor"]], "侧面图")
    back = _first_image_or_error([results_by_key["back"]["tensor"]], "背面图")
    batch = _cat_image_batches_safe([front, side, back])

    runtime_cache_key = _cache_key_or_default(cache_key)
    _publish_runtime_result(
        cache_key=runtime_cache_key,
        labels_prefix=labels_prefix,
        model=model,
        image_size=image_size,
        aspect_ratio=aspect_ratio,
        generate_scope=scope,
        results_by_key=results_by_key,
        errors_by_key=errors_by_key,
    )

    return {
        "front": front,
        "side": side,
        "back": back,
        "batch": batch,
        "ordered": ordered,
        "results_by_key": results_by_key,
        "errors_by_key": errors_by_key,
        "generate_scope": scope,
        "active_keys": list(active_keys),
        "cache_key": runtime_cache_key,
        "auto_retry_until_success": auto_retry_until_success,
        "max_retry_per_view": max_retry_per_view,
        "retry_interval_sec": retry_interval_sec,
    }

def _compose_manual_prompt(global_prompt: str, view_prompt: str, negative_prompt: str = "") -> str:
    """三方案节点只使用三个独立方案提示词；global_prompt / negative_prompt 仅保留兼容旧工作流。"""
    return str(view_prompt or "").strip()




_AUTOMATION_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _auto_extract_sequence(name: str) -> str:
    parts = re.findall(r"\d+", str(name or ""))
    return "".join(parts) if parts else ""


def _auto_sequence_sort_key(seq: str):
    text = str(seq or "")
    try:
        return (0, int(text), len(text), text)
    except Exception:
        return (1, 0, len(text), text)


def _auto_clean_path_list(values: Any, max_count: int = 10) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    seen = set()
    for item in values:
        path = str(item or "").strip().strip('"')
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
        if len(out) >= max_count:
            break
    return out


def _auto_clean_sequence_list(values: Any, max_count: int = 9999) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    out: List[str] = []
    seen = set()
    for item in values:
        raw = str(item or "").strip().strip('"')
        if not raw:
            continue
        seq = _auto_extract_sequence(raw) or raw
        if not seq or seq in seen:
            continue
        seen.add(seq)
        out.append(seq)
        if len(out) >= max_count:
            break
    return out


def _auto_payload_from_string(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _automation_enabled(raw: Any) -> bool:
    data = _auto_payload_from_string(raw)
    # 只要节点后台存在有效自动化 JSON，就默认执行自动化；只有明确 enabled=false 才禁用。
    if not data:
        return False
    return _value_as_bool(data.get("enabled"), True)


def _default_automation_output_root() -> str:
    """
    自动化输出根目录兜底。

    用户可以不选择输出目录；为空时自动写到 ComfyUI/output/hrio_design_automation。
    在非标准环境里取不到 ComfyUI 输出目录时，写到插件目录 hrio_design_automation_outputs。
    """
    candidates: List[str] = []

    try:
        import folder_paths  # type: ignore
        output_dir = folder_paths.get_output_directory()
        if output_dir:
            candidates.append(os.path.join(str(output_dir), "hrio_design_automation"))
    except Exception:
        pass

    candidates.append(os.path.join(MODULE_DIR, "hrio_design_automation_outputs"))

    for path in candidates:
        path = str(path or "").strip()
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            continue

    return os.path.join(MODULE_DIR, "hrio_design_automation_outputs")


def _auto_normalize_preview_groups(value: Any, output_root: str = "") -> List[Dict[str, Any]]:
    """
    规范化前端 JSON 里的 preview_groups。

    这样即使 ComfyUI 运行时没有重新预览，也可以直接按照 JSON
    中的 image_path / items 执行；同时兼容 output_root 为空时的默认输出目录。
    """
    if not isinstance(value, list):
        return []

    groups: List[Dict[str, Any]] = []
    for raw_group in value:
        if not isinstance(raw_group, dict):
            continue

        seq = str(raw_group.get("sequence") or raw_group.get("seq") or "").strip()
        if not seq:
            seq = _auto_extract_sequence(str(raw_group.get("name") or raw_group.get("output_dir") or ""))
        if not seq:
            continue

        items: List[Dict[str, Any]] = []
        raw_items = raw_group.get("items") or raw_group.get("images") or raw_group.get("files") or []
        if not isinstance(raw_items, list):
            raw_items = []

        for idx, raw_item in enumerate(raw_items):
            if isinstance(raw_item, str):
                image_path = raw_item
                file_name = os.path.basename(raw_item)
                root_path = ""
                root_index = idx
            elif isinstance(raw_item, dict):
                image_path = str(
                    raw_item.get("image_path")
                    or raw_item.get("path")
                    or raw_item.get("file_path")
                    or raw_item.get("full_path")
                    or ""
                ).strip()
                file_name = str(raw_item.get("file_name") or os.path.basename(image_path)).strip()
                root_path = str(raw_item.get("root_path") or raw_item.get("input_root") or "").strip()
                root_index = _safe_int(raw_item.get("root_index", idx), idx, 0, 999)
            else:
                continue

            if not image_path:
                continue

            items.append({
                "root_index": root_index,
                "root_path": root_path,
                "source_type": "preview_group_image",
                "file_name": file_name or os.path.basename(image_path),
                "image_path": image_path,
                "sequence": seq,
                "relative_path": str(raw_item.get("relative_path") or "") if isinstance(raw_item, dict) else "",
            })

        if not items:
            continue

        run_dir = str(raw_group.get("output_dir") or "").strip()
        if not run_dir and output_root:
            run_dir = os.path.join(str(output_root), f"output_{seq}", "run_01")

        expected = _safe_int(raw_group.get("expected_root_count", len(items)), len(items), 0, 999)
        present = _safe_int(raw_group.get("present_root_count", len(items)), len(items), 0, 999)
        groups.append({
            "sequence": seq,
            "items": sorted(items, key=lambda x: int(x.get("root_index") or 0)),
            "output_dir": run_dir,
            "present_root_count": present or len(items),
            "expected_root_count": expected or len(items),
        })

    groups.sort(key=lambda x: _auto_sequence_sort_key(str(x.get("sequence") or "")))
    return groups


def _auto_normalize_payload(raw: Any, *, save_images_default: bool = True, save_video_default: bool = False) -> Dict[str, Any]:
    data = _auto_payload_from_string(raw)
    input_roots = _auto_clean_path_list(data.get("input_roots") or data.get("inputFolders") or data.get("input_folders"), 10)
    output_root = str(data.get("output_root") or data.get("outputRoot") or "").strip()
    if not output_root:
        output_root = _default_automation_output_root()
    group_concurrency = _safe_int(data.get("group_concurrency", data.get("groupConcurrency", 3)), 3, 1, 10)
    max_images_per_group = _safe_int(data.get("max_images_per_group", data.get("maxImagesPerGroup", 10)), 10, 1, 10)
    require_all = _value_as_bool(data.get("require_all_roots_present"), False)
    run_sequences = _auto_clean_sequence_list(
        data.get("run_sequences")
        or data.get("target_sequences")
        or data.get("sequences")
        or data.get("run_sequence")
        or data.get("runSequence")
        or data.get("selected_sequence")
        or data.get("sequence")
    )
    run_view = str(data.get("run_view") or data.get("view") or "").strip()
    run_mode = str(data.get("run_mode") or data.get("action") or "").strip()
    preview_groups = _auto_normalize_preview_groups(data.get("preview_groups") or data.get("previewGroups") or [], output_root)
    # 如果 JSON 只有 preview_groups，没有 input_roots，也从 group 里反推出根目录，方便“复制 JSON 后直接运行”。
    if not input_roots and preview_groups:
        inferred_roots: List[str] = []
        for group in preview_groups:
            for item in group.get("items") or []:
                root = str(item.get("root_path") or "").strip()
                if root and root not in inferred_roots:
                    inferred_roots.append(root)
        input_roots = inferred_roots[:10]
    return {
        "enabled": _value_as_bool(data.get("enabled"), True),
        "version": str(data.get("version") or "8.2.2"),
        "input_roots": input_roots,
        "preview_groups": preview_groups,
        "output_root": output_root,
        "group_concurrency": group_concurrency,
        "max_input_roots": 10,
        "max_images_per_group": max_images_per_group,
        "extract_rule": "greedy_digits_join_all",
        "collect_images_mode": "root_images_group_by_filename_sequence",
        "collect_mode": "root_images_group_by_filename_sequence",
        "require_all_roots_present": require_all,
        "save_images": _value_as_bool(data.get("save_images"), save_images_default),
        "save_video": _value_as_bool(data.get("save_video"), save_video_default),
        "run_sequences": run_sequences,
        "run_view": run_view,
        "run_mode": run_mode,
        "video_filename": str(data.get("video_filename") or "result.mp4"),
        "image_filenames": data.get("image_filenames") if isinstance(data.get("image_filenames"), dict) else {
            "front": "front.png",
            "side": "side.png",
            "back": "back.png",
            "single": "single.png",
        },
    }


def _scan_input_root_images(root: str) -> List[Dict[str, Any]]:
    """
    递归扫描输入根目录。

    规则：
    - 优先从图片文件名提取数字序号，例如 001.png -> 001；
    - 文件名没有数字时，从最近的父文件夹提取数字，例如 001/front.png -> 001；
    - 兼容 Windows 路径和 Unicode 文件名；
    - 只返回本地存在的图片文件，避免后续上传阶段才失败。
    """
    items: List[Dict[str, Any]] = []
    root = str(root or "").strip().strip('"')
    if not root or not os.path.isdir(root):
        return items

    try:
        walker = os.walk(root)
        for dirpath, _dirnames, filenames in walker:
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                if not os.path.isfile(full):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in _AUTOMATION_IMAGE_EXTS:
                    continue

                stem = os.path.splitext(name)[0]
                seq = _auto_extract_sequence(stem)
                if not seq:
                    rel_dir = os.path.relpath(dirpath, root)
                    parts = [] if rel_dir in {".", ""} else list(reversed(rel_dir.split(os.sep)))
                    for part in parts:
                        seq = _auto_extract_sequence(part)
                        if seq:
                            break

                if not seq:
                    continue

                try:
                    rel = os.path.relpath(full, root)
                except Exception:
                    rel = name

                items.append({
                    "source_type": "root_image",
                    "file_name": name,
                    "relative_path": rel,
                    "image_path": full,
                    "sequence": seq,
                })
    except Exception as e:
        logger.warning(f"自动化扫描输入目录失败: {root} | {e}")
        return items

    return items


def _build_automation_sequence_groups(input_roots: List[str], output_root: str = "", require_all_roots_present: bool = False) -> List[Dict[str, Any]]:
    group_map: Dict[str, List[Dict[str, Any]]] = {}
    root_count = len(input_roots)
    for root_index, root in enumerate(input_roots):
        for item in _scan_input_root_images(root):
            seq = item["sequence"]
            group_map.setdefault(seq, []).append({
                "root_index": root_index,
                "root_path": root,
                "source_type": "root_image",
                "file_name": item["file_name"],
                "image_path": item["image_path"],
                "sequence": seq,
            })
    groups: List[Dict[str, Any]] = []
    for seq in sorted(group_map.keys(), key=_auto_sequence_sort_key):
        items = sorted(group_map[seq], key=lambda x: int(x.get("root_index") or 0))
        present_roots = {int(x.get("root_index") or 0) for x in items}
        if require_all_roots_present and len(present_roots) < root_count:
            continue
        run_dir = os.path.join(str(output_root or ""), f"output_{seq}", "run_01") if output_root else ""
        groups.append({
            "sequence": seq,
            "items": items,
            "output_dir": run_dir,
            "present_root_count": len(present_roots),
            "expected_root_count": root_count,
        })
    return groups


def _build_automation_sequence_groups_from_cfg(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    自动化统一分组入口。

    优先实时扫描 input_roots；如果扫描不到，自动回退到 JSON 里已经保存的
    preview_groups。这样“应用到节点 / 应用并运行全部 / 跑本组”都不依赖
    前端必须再次预览，也不会因为 output_root 为空而无法运行。
    """
    input_roots = cfg.get("input_roots") or []
    groups: List[Dict[str, Any]] = []
    if input_roots:
        groups = _build_automation_sequence_groups(
            input_roots,
            output_root=str(cfg.get("output_root") or ""),
            require_all_roots_present=bool(cfg.get("require_all_roots_present")),
        )

    if not groups and isinstance(cfg.get("preview_groups"), list):
        groups = list(cfg.get("preview_groups") or [])
        # 确保旧 JSON 里 output_dir 为空时也有默认输出目录。
        for group in groups:
            if not isinstance(group, dict):
                continue
            seq = str(group.get("sequence") or "").strip()
            if seq and not str(group.get("output_dir") or "").strip():
                group["output_dir"] = os.path.join(str(cfg.get("output_root") or _default_automation_output_root()), f"output_{seq}", "run_01")

    groups = [g for g in groups if isinstance(g, dict) and str(g.get("sequence") or "").strip()]
    groups.sort(key=lambda x: _auto_sequence_sort_key(str(x.get("sequence") or "")))
    return groups


def _collect_automation_group_images(items: List[Dict[str, Any]], max_count: int = 10) -> List[str]:
    paths: List[str] = []
    for item in sorted(items or [], key=lambda x: int(x.get("root_index") or 0)):
        image_path = str(item.get("image_path") or "")
        if not image_path or not os.path.isfile(image_path):
            continue
        ext = os.path.splitext(image_path)[1].lower()
        if ext in _AUTOMATION_IMAGE_EXTS:
            paths.append(image_path)
            if len(paths) >= max_count:
                return paths
    return paths[:max_count]


def _load_image_tensors_from_paths(paths: List[str]) -> List[torch.Tensor]:
    tensors: List[torch.Tensor] = []
    for path in paths:
        path = str(path or "").strip().strip('"')
        if not path:
            continue
        try:
            # ImageOps.exif_transpose 避免手机照片方向错误；逐张容错，坏图不会拖垮整组。
            from PIL import ImageOps
            img = Image.open(path)
            img = ImageOps.exif_transpose(img).convert("RGB")
            tensors.append(_pil_to_tensor(img))
        except Exception as e:
            logger.warning(f"自动化图片读取失败，已跳过: {path} | {e}")
    return tensors


def _save_tensor_image(tensor: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = tensor.detach().cpu()
    if t.ndim == 4:
        t = t[0]
    arr = (t.clamp(0, 1).numpy() * 255).astype(np.uint8)
    Image.fromarray(arr).save(path)


def _write_text_file(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(text or ""))


def _save_binary_file(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data or b"")


def _automation_history_path() -> str:
    return os.path.join(MODULE_DIR, AUTOMATION_HISTORY_FILE)


def _automation_history_now_ms() -> int:
    return int(time.time() * 1000)


def _automation_history_existing_files(output_dir: str) -> Dict[str, str]:
    output_dir = str(output_dir or "")
    names = ["front.png", "side.png", "back.png", "single.png", "single_image.png", "result.png", "result.mp4", "run_info.json", "error.txt"]
    out: Dict[str, str] = {}
    for name in names:
        path = os.path.join(output_dir, name) if output_dir else ""
        if path and os.path.exists(path):
            out[name] = path
    return out


def _comfyui_media_ref_from_path(path: Any) -> Dict[str, Any]:
    raw = str(path or "").strip()
    if not raw:
        return {}
    abs_path = os.path.abspath(raw)
    name = os.path.basename(abs_path)
    ext = os.path.splitext(name)[1].lower()
    kind = "video" if ext in {".mp4", ".mov", ".webm", ".m4v"} else "image"
    ref: Dict[str, Any] = {
        "name": name,
        "path": abs_path,
        "kind": kind,
        "ext": ext,
    }
    try:
        import folder_paths  # type: ignore
        roots = [
            (folder_paths.get_output_directory(), "output"),
            (folder_paths.get_temp_directory(), "temp"),
            (folder_paths.get_input_directory(), "input"),
        ]
        for root, media_type in roots:
            root_abs = os.path.abspath(str(root or ""))
            if not root_abs:
                continue
            try:
                common = os.path.commonpath([root_abs, abs_path])
            except Exception:
                common = ""
            if common == root_abs:
                rel = os.path.relpath(abs_path, root_abs)
                subfolder = os.path.dirname(rel).replace("\\", "/")
                filename = os.path.basename(rel)
                ref.update({
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": media_type,
                    "view_url": _comfyui_view_url(filename, media_type, subfolder),
                    "url": _comfyui_view_url(filename, media_type, subfolder),
                })
                break
    except Exception:
        pass
    return ref


def _automation_history_media_items(output_dir: str) -> List[Dict[str, Any]]:
    files = _automation_history_existing_files(output_dir)
    media: List[Dict[str, Any]] = []
    for key in ("front.png", "side.png", "back.png", "single.png", "single_image.png", "result.png", "result.mp4"):
        path = files.get(key)
        if not path:
            continue
        ref = _comfyui_media_ref_from_path(path)
        if ref:
            ref["slot"] = key
            media.append(ref)
    return media


def _read_automation_history_file() -> Dict[str, Any]:
    path = _automation_history_path()
    if not os.path.exists(path):
        return {"ok": True, "version": "8.2.3", "updated_at_ms": 0, "count": 0, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"ok": True, "version": "8.2.3", "updated_at_ms": 0, "count": 0, "items": []}
    if not isinstance(data, dict):
        data = {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return {
        "ok": True,
        "version": str(data.get("version") or "8.2.2"),
        "updated_at_ms": int(data.get("updated_at_ms") or 0),
        "count": len(items),
        "items": items[-_AUTOMATION_HISTORY_MAX_ITEMS:],
    }


def _append_automation_history_record(record: Dict[str, Any]) -> None:
    if not isinstance(record, dict):
        return
    item = dict(record)
    for key in ("front", "side", "back", "batch", "tensor", "image"):
        item.pop(key, None)
    output_dir = str(item.get("output_dir") or "")
    item.setdefault("output_files", _automation_history_existing_files(output_dir))
    item.setdefault("media", _automation_history_media_items(output_dir))
    item.setdefault("created_at_ms", _automation_history_now_ms())
    item.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    item.setdefault("plugin_version", "8.2.2")
    with _AUTOMATION_HISTORY_LOCK:
        data = _read_automation_history_file()
        items = data.get("items") if isinstance(data.get("items"), list) else []
        items.append(item)
        items = items[-_AUTOMATION_HISTORY_MAX_ITEMS:]
        payload = {
            "ok": True,
            "version": "8.2.3",
            "updated_at_ms": _automation_history_now_ms(),
            "count": len(items),
            "items": items,
        }
        with open(_automation_history_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # 同步写入轻量运行期 JSON 缓存，供“最近生成”和“全部生成历史”直接加载。
    try:
        group = _history_item_to_runtime_group(item)
        video = _history_item_to_runtime_video(item)
        _runtime_file_upsert(groups=[group] if group else [], videos=[video] if video else [])
    except Exception as e:
        logger.warning(f"自动化历史同步到运行期 JSON 缓存失败: {e}")


def _run_three_view_automation_group(
    *,
    group: Dict[str, Any],
    cfg: Dict[str, Any],
    api_key: str,
    model: str,
    image_size: str,
    aspect_ratio: str,
    prompts: Dict[str, str],
    labels: str,
    cache_key: str,
    auto_retry_until_success: bool,
    max_retry_per_view: int,
    retry_interval_sec: float,
    generate_scope: str = "全部并发生成",
) -> Dict[str, Any]:
    seq = str(group.get("sequence") or "")
    run_dir = str(group.get("output_dir") or os.path.join(cfg["output_root"], f"output_{seq}", "run_01"))
    os.makedirs(run_dir, exist_ok=True)
    try:
        image_paths = _collect_automation_group_images(group.get("items") or [], int(cfg.get("max_images_per_group") or 10))
        if not image_paths:
            raise RuntimeError(f"序号 {seq} 没有找到可用图片")
        tensors = _load_image_tensors_from_paths(image_paths)
        if not tensors:
            raise RuntimeError(f"序号 {seq} 图片读取失败，没有可上传的有效图片")
        upload_dir = _cfg_or_manifest("upload_dir", "uploads/images")
        image_urls = _tensors_to_uploaded_urls(tensors, api_key, upload_dir)
        result = _run_three_view_jobs(
            api_key=api_key,
            model=model,
            image_size=image_size,
            aspect_ratio=aspect_ratio,
            image_urls=image_urls,
            prompts=prompts,
            labels_prefix=f"{labels}-自动化{seq}-" if labels else f"自动化{seq}-",
            generate_scope=generate_scope,
            cache_key=f"{cache_key}:{seq}",
            auto_retry_until_success=auto_retry_until_success,
            max_retry_per_view=max_retry_per_view,
            retry_interval_sec=retry_interval_sec,
        )
        image_names = cfg.get("image_filenames") or {}
        if bool(cfg.get("save_images", True)):
            _save_tensor_image(result["front"], os.path.join(run_dir, str(image_names.get("front") or "front.png")))
            _save_tensor_image(result["side"], os.path.join(run_dir, str(image_names.get("side") or "side.png")))
            _save_tensor_image(result["back"], os.path.join(run_dir, str(image_names.get("back") or "back.png")))
        meta = {
            "sequence": seq,
            "ok": True,
            "run_id": f"normal_three_view:{seq}:{_automation_history_now_ms()}",
            "node_type": "normal_three_view",
            "output_dir": run_dir,
            "input_image_count": len(image_paths),
            "uploaded_image_count": len(image_urls),
            "source_images": image_paths,
            "errors_by_key": result.get("errors_by_key") or {},
            "generate_scope": result.get("generate_scope") or generate_scope,
            "model": model,
            "image_size": image_size,
            "aspect_ratio": aspect_ratio,
            "labels": labels,
        }
        _write_text_file(os.path.join(run_dir, "run_info.json"), json.dumps(meta, ensure_ascii=False, indent=2))
        _append_automation_history_record(meta)
        return {**meta, "front": result.get("front"), "side": result.get("side"), "back": result.get("back"), "batch": result.get("batch")}
    except Exception as e:
        _write_text_file(os.path.join(run_dir, "error.txt"), f"{type(e).__name__}: {e}")
        logger.error(f"自动化序号 {seq} 失败: {e}")
        fail_meta = {"sequence": seq, "ok": False, "node_type": "normal_three_view", "output_dir": run_dir, "error": str(e), "model": model, "image_size": image_size, "aspect_ratio": aspect_ratio, "labels": labels}
        _append_automation_history_record(fail_meta)
        return fail_meta



def _run_single_image_automation_group(
    *,
    group: Dict[str, Any],
    cfg: Dict[str, Any],
    api_key: str,
    prompt: str,
    model: str,
    image_size: str,
    aspect_ratio: str,
    negative_prompt: str = "",
    cache_key: str = "",
) -> Dict[str, Any]:
    """普通单图节点的自动化单组执行。"""
    seq = str(group.get("sequence") or "")
    run_dir = str(group.get("output_dir") or os.path.join(cfg["output_root"], f"output_{seq}", "run_01"))
    os.makedirs(run_dir, exist_ok=True)
    try:
        image_paths = _collect_automation_group_images(
            group.get("items") or [],
            int(cfg.get("max_images_per_group") or 10),
        )
        if not image_paths:
            raise RuntimeError(f"序号 {seq} 没有找到可用图片")

        tensors = _load_image_tensors_from_paths(image_paths)
        if not tensors:
            raise RuntimeError(f"序号 {seq} 图片读取失败，没有可上传的有效图片")
        upload_dir = _cfg_or_manifest("upload_dir", "uploads/images")
        image_urls = _tensors_to_uploaded_urls(tensors, api_key, upload_dir)
        final_prompt = _compose_single_image_prompt(prompt, negative_prompt)

        item = _single_image_generation_job(
            f"普通单图自动化{seq}",
            _node_base_values(
                api_key,
                final_prompt,
                model,
                image_size,
                aspect_ratio,
                auto_retry_until_success=True,
                max_retry_per_view=_safe_int(_cfg_or_manifest("max_retry_per_view", "6"), 6, 1, 999),
                retry_interval_sec=_safe_float(_cfg_or_manifest("retry_interval_sec", "1.5"), 1.5, 0.1, 30.0),
            ),
            image_urls,
        )

        image_out = item.get("tensor")
        if image_out is None:
            raise RuntimeError("普通单图自动化没有返回图片")

        image_names = cfg.get("image_filenames") if isinstance(cfg.get("image_filenames"), dict) else {}
        image_name = str(image_names.get("single") or image_names.get("image") or "single.png")
        local_image_path = ""
        if bool(cfg.get("save_images", True)):
            local_image_path = os.path.join(run_dir, image_name)
            _save_tensor_image(image_out, local_image_path)

        meta = {
            "sequence": seq,
            "ok": True,
            "run_id": f"normal_single_image:{seq}:{_automation_history_now_ms()}",
            "node_type": "normal_single_image",
            "output_dir": run_dir,
            "input_image_count": len(image_paths),
            "uploaded_image_count": len(image_urls),
            "source_images": image_paths,
            "local_image_path": local_image_path,
            "model": item.get("model") or model,
            "display_model": item.get("display_model") or model,
            "image_size": item.get("image_size") or image_size,
            "aspect_ratio": item.get("aspect_ratio") or aspect_ratio,
            "seed": item.get("seed"),
            "attempt": item.get("attempt"),
            "note": "普通单图自动化会把同序号输入图作为参考图，输出一张 single.png。",
        }
        _publish_single_image_runtime_result(
            cache_key=f"{cache_key}:{seq}" if cache_key else f"normal_single_image_automation:{seq}",
            label=f"普通单图自动化 · 序号 {seq}",
            model=str(item.get("display_model") or item.get("model") or model),
            image_size=str(item.get("image_size") or image_size),
            aspect_ratio=str(item.get("aspect_ratio") or aspect_ratio),
            tensor=image_out,
        )
        _write_text_file(os.path.join(run_dir, "run_info.json"), json.dumps(meta, ensure_ascii=False, indent=2))
        _append_automation_history_record(meta)
        return {**meta, "image": image_out}
    except Exception as e:
        _write_text_file(os.path.join(run_dir, "error.txt"), f"{type(e).__name__}: {e}")
        logger.error(f"普通单图自动化序号 {seq} 失败: {e}")
        _publish_single_image_runtime_result(
            cache_key=f"{cache_key}:{seq}" if cache_key else f"normal_single_image_automation:{seq}",
            label=f"普通单图自动化 · 序号 {seq}",
            model=model,
            image_size=image_size,
            aspect_ratio=aspect_ratio,
            tensor=None,
            error=str(e),
        )
        fail_meta = {
            "sequence": seq,
            "ok": False,
            "run_id": f"normal_single_image:{seq}:{_automation_history_now_ms()}",
            "node_type": "normal_single_image",
            "output_dir": run_dir,
            "error": str(e),
            "model": model,
            "image_size": image_size,
            "aspect_ratio": aspect_ratio,
        }
        _append_automation_history_record(fail_meta)
        return fail_meta

def _run_video_automation_group(
    *,
    group: Dict[str, Any],
    cfg: Dict[str, Any],
    api_key: str,
    prompt: str,
    video_model: str,
    video_resolution: str = "1080p",
    aspect_ratio: str = "16:9 (横屏宽幅)",
) -> Dict[str, Any]:
    """
    生视频自动化单组执行。

    说明：
    - 视频节点 UI 暴露 prompt / video_model / image_1...image_10；
    - 自动化时从 input_roots 里按同序号收集最多 4 张图，匹配当前后端 image + referenceImages 上限；
    - 图片会先上传为 OSS/COS 公网 URL，再随提示词传给视频接口；
    - 输出默认走 OSS，并把返回的 mp4 地址下载保存为 result.mp4。
    """
    seq = str(group.get("sequence") or "")
    run_dir = str(group.get("output_dir") or os.path.join(cfg["output_root"], f"output_{seq}", "run_01"))
    os.makedirs(run_dir, exist_ok=True)
    try:
        image_paths = _collect_automation_group_images(group.get("items") or [], min(4, int(cfg.get("max_images_per_group") or 10)))
        if not image_paths:
            raise RuntimeError(f"序号 {seq} 没有找到可用图片")

        tensors = _load_image_tensors_from_paths(image_paths)
        if not tensors:
            raise RuntimeError(f"序号 {seq} 图片读取失败，没有可上传的有效图片")
        upload_dir = _cfg_or_manifest("upload_dir", "uploads/images")
        image_urls = _tensors_to_uploaded_urls(tensors, api_key, upload_dir)

        result = _generate_video_from_prompt(
            api_key,
            prompt,
            video_model,
            image_urls=image_urls,
            video_resolution=video_resolution,
            aspect_ratio=aspect_ratio,
        )
        mp4url = str(result.get("mp4url") or "")

        local_video_path = ""
        if bool(cfg.get("save_video", True)) and mp4url:
            local_video_path = os.path.join(run_dir, str(cfg.get("video_filename") or "result.mp4"))
            raw = _download_binary(mp4url)
            _save_binary_file(local_video_path, raw)

        meta = {
            "sequence": seq,
            "ok": True,
            "run_id": f"video:{seq}:{_automation_history_now_ms()}",
            "node_type": "video",
            "output_dir": run_dir,
            "input_image_count": len(image_paths),
            "uploaded_image_count": len(image_urls),
            "source_images": image_paths,
            "mp4url": mp4url,
            "local_video_path": local_video_path,
            "display_model": result.get("display_model"),
            "model": result.get("model"),
            "action": result.get("action"),
            "operation": result.get("operation") or "",
            "ref_image_count": result.get("ref_image_count") or len(image_urls),
            "video_resolution": result.get("video_resolution") or _normalize_video_resolution(video_resolution),
            "aspect_ratio": result.get("aspect_ratio") or _normalize_video_aspect_ratio(aspect_ratio),
            "note": "视频自动化会把每个序号组最多 4 张图片作为参考图传入视频接口，匹配当前后端 referenceImages 上限。",
        }
        _write_text_file(os.path.join(run_dir, "run_info.json"), json.dumps(meta, ensure_ascii=False, indent=2))
        _append_automation_history_record(meta)
        return meta
    except Exception as e:
        _write_text_file(os.path.join(run_dir, "error.txt"), f"{type(e).__name__}: {e}")
        logger.error(f"视频自动化序号 {seq} 失败: {e}")
        fail_meta = {
            "sequence": seq,
            "ok": False,
            "run_id": f"video:{seq}:{_automation_history_now_ms()}",
            "node_type": "video",
            "output_dir": run_dir,
            "error": str(e),
            "model": video_model,
            "video_resolution": _normalize_video_resolution(video_resolution),
            "aspect_ratio": _normalize_video_aspect_ratio(aspect_ratio),
        }
        _append_automation_history_record(fail_meta)
        return fail_meta


def _run_video_automation_batch(
    *,
    resolved_key: str,
    prompt: str,
    video_model: str,
    video_resolution: str,
    aspect_ratio: str,
    automation_payload: str,
    output_kind: str = "video",
) -> Dict[str, Any]:
    start = time.time()
    cfg = _auto_normalize_payload(automation_payload, save_images_default=False, save_video_default=True)
    if not cfg.get("input_roots") and not cfg.get("preview_groups"):
        return {"ok": False, "error": "自动化已启用，但没有 input_roots / preview_groups。", "lines": ["❌ Hrio Design 生视频自动化失败", "自动化已启用，但没有 input_roots / preview_groups。"]}

    groups = _build_automation_sequence_groups_from_cfg(cfg)
    all_group_count = len(groups)
    run_sequences = set(str(x) for x in (cfg.get("run_sequences") or []) if str(x).strip())
    if run_sequences:
        groups = [g for g in groups if str(g.get("sequence") or "") in run_sequences]
    if not groups:
        if run_sequences:
            msg = f"自动化没有找到指定序号组：{', '.join(sorted(run_sequences))}。"
        else:
            msg = "自动化没有扫描到任何有效序号组。"
        return {"ok": False, "error": msg, "lines": ["❌ Hrio Design 生视频自动化失败", msg]}

    group_concurrency = int(cfg.get("group_concurrency") or 3)
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(10, group_concurrency))) as executor:
        futures = [
            executor.submit(
                _run_video_automation_group,
                group=group,
                cfg=cfg,
                api_key=resolved_key,
                prompt=prompt,
                video_model=video_model,
                video_resolution=video_resolution,
                aspect_ratio=aspect_ratio,
            )
            for group in groups
        ]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda x: _auto_sequence_sort_key(str(x.get("sequence") or "")))
    ok_results = [r for r in results if r.get("ok")]
    fail_results = [r for r in results if not r.get("ok")]
    elapsed = time.time() - start
    last_ok = (ok_results[-1] if ok_results else {})
    mp4url = str(last_ok.get("mp4url") or "")
    local_video_path = str(last_ok.get("local_video_path") or "")
    title = "普通单输出视频自动化批处理完成" if output_kind == "normal_video_single" else "Hrio Design 生视频自动化批处理完成"
    lines = [
        f"✅ {title}，耗时 {elapsed:.1f}s",
        f"video_model: {video_model}",
        f"video_resolution: {_normalize_video_resolution(video_resolution)}",
        f"aspect_ratio: {_normalize_video_aspect_ratio(aspect_ratio)}",
        "enable_oss: True",
        f"input_roots: {len(cfg.get('input_roots') or [])}",
        f"groups: {len(groups)} / all_groups: {all_group_count}",
        f"run_sequences: {', '.join(sorted(run_sequences)) if run_sequences else '全部'}",
        f"success: {len(ok_results)}",
        f"failed: {len(fail_results)}",
        f"group_concurrency: {group_concurrency}",
        f"max_images_per_group: {cfg.get('max_images_per_group')}",
        f"output_root: {cfg['output_root']}",
        "输入规则: 只扫描输入根目录下的直接图片文件，例如 input_root_01/001.png；输出目录规则: output_序号/run_01/，视频文件 result.mp4。",
    ]
    for r in results:
        if r.get("ok"):
            lines.append(f"✅ {r.get('sequence')} -> {r.get('output_dir')} | 输入图片 {r.get('input_image_count')} 张 | mp4={r.get('mp4url')}")
        else:
            lines.append(f"❌ {r.get('sequence')} -> {r.get('output_dir')} | {r.get('error')}")

    return {
        "ok": True,
        "lines": lines,
        "results": results,
        "mp4url": mp4url,
        "local_video_path": local_video_path,
        "success": len(ok_results),
        "failed": len(fail_results),
    }


class HrioBananaNormalThreeViewConcurrentNodeV330:
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("front_image", "side_image", "back_image", "images", "info", "mp4url")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = str((_MANIFEST.get("normal_three_view", {}) or {}).get("category") or "HRIO设计/普通")

    @classmethod
    def INPUT_TYPES(cls):
        cfg = _MANIFEST.get("normal_three_view", {}) or {}

        model_options = _enum_source_options("model_map", ["banano2", "banano-pro", "gemini3.1-pro"])
        image_size_options = _enum_source_options("image_size_options", ["1K", "2K", "4K", "8K（默认16:9）"])
        aspect_options = _enum_source_options(
            "aspect_ratio_options",
            ["Auto", "1:1 (方形)", "3:4 (竖屏标准)", "9:16 (竖屏/手机)", "16:9 (横屏宽幅)"],
        )

        default_model = _enum_source_display("model_map", cfg.get("default_model") or _cfg_or_manifest("model", "banano"), "banano2")
        default_size = _enum_source_display("image_size_options", cfg.get("default_image_size") or _cfg_or_manifest("image_size", "2K"), "2K")
        default_ratio = _enum_source_display("aspect_ratio_options", cfg.get("default_aspect_ratio") or _cfg_or_manifest("aspect_ratio", "Auto"), "Auto")

        required = {
            "api_key": ("STRING", {"default": _cfg("api_key", ""), "multiline": False, "tooltip": "填入 API Key；留空时尝试读取 config.ini 的 api_key"}),
            "front_prompt": ("STRING", {"default": "方案 A：设计主方案。基于参考图生成一张高审美平面设计或室内设计提案图，构图稳定、层级清晰、材质自然、光影干净，适合正式商业提案。", "multiline": True, "tooltip": "方案 A 提示词。普通三方案并发节点会按这里生成第一张方案图。"}),
            "side_prompt": ("STRING", {"default": "方案 B：氛围强化方案。在保持同一设计方向的基础上，强化空间层次、材质细节、视觉冲击力和情绪氛围，适合客户展示和方案比选。", "multiline": True, "tooltip": "方案 B 提示词。普通三方案并发节点会按这里生成第二张方案图。"}),
            "back_prompt": ("STRING", {"default": "方案 C：创意延展方案。更强调设计张力、风格记忆点、抽象图形、空间关系或软装搭配，但仍保持高级、克制、真实可落地。", "multiline": True, "tooltip": "方案 C 提示词。普通三方案并发节点会按这里生成第三张方案图。"}),
            "model": (model_options, {"default": default_model if default_model in model_options else model_options[0], "tooltip": "图片模型；三视图会并发请求三次"}),
            "image_size": (image_size_options, {"default": default_size if default_size in image_size_options else "2K", "tooltip": "三张图使用同一尺寸"}),
            "aspect_ratio": (aspect_options, {"default": default_ratio if default_ratio in aspect_options else "Auto", "tooltip": "三张图使用同一宽高比"}),
            "generate_scope": (_THREE_VIEW_SCOPE_OPTIONS, {"default": "全部并发生成", "tooltip": "质量不满意时可只重新生成某一个视图；其他视图会使用本节点上一次成功缓存结果。"}),
        }

        optional = {
            "automation_payload": _automation_payload_widget(),
        }

        slot_count = int(cfg.get("optional_image_slots") or _NODE.get("optional_image_slots", 10) or 10)
        for i in range(1, slot_count + 1):
            optional[f"image_{i}"] = ("IMAGE", {"tooltip": f"参考图 {i}；同一批上传图会复用到正面/侧面/背面三个并发请求"})

        return {"required": required, "optional": optional, "hidden": {"unique_id": "UNIQUE_ID", "prompt_graph": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

    def generate(
        self,
        api_key: str,
        front_prompt: str,
        side_prompt: str,
        back_prompt: str,
        model: str,
        image_size: str,
        aspect_ratio: str,
        generate_scope: str = "全部并发生成",
        auto_retry_until_success: bool = True,
        max_retry_per_view: int = 8,
        retry_interval_sec: float = 1.5,
        global_prompt: str = "",
        negative_prompt: str = "",
        automation_payload: str = "",
        unique_id=None,
        prompt_graph=None,
        extra_pnginfo=None,
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")
        automation_payload = _resolve_automation_payload(
            automation_payload,
            unique_id=unique_id,
            prompt=prompt_graph,
            extra_pnginfo=extra_pnginfo,
            values=kwargs,
        )

        if not resolved_key:
            msg = "请在节点中填入 API Key"
            logger.error(msg)
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")

        if _automation_enabled(automation_payload):
            return self.generate_automation(
                resolved_key=resolved_key,
                front_prompt=front_prompt,
                side_prompt=side_prompt,
                back_prompt=back_prompt,
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                auto_retry_until_success=auto_retry_until_success,
                max_retry_per_view=max_retry_per_view,
                retry_interval_sec=retry_interval_sec,
                generate_scope=generate_scope,
                global_prompt=global_prompt,
                negative_prompt=negative_prompt,
                automation_payload=automation_payload,
                unique_id=unique_id,
            )

        try:
            image_urls = _upload_reference_images_for_node(kwargs, resolved_key)
        except Exception as e:
            msg = f"参考图上传失败: {e}"
            logger.error(msg)
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")

        prompts = {
            "front": _compose_manual_prompt(global_prompt, front_prompt, negative_prompt),
            "side": _compose_manual_prompt(global_prompt, side_prompt, negative_prompt),
            "back": _compose_manual_prompt(global_prompt, back_prompt, negative_prompt),
        }

        logger.info(
            f"普通三方案并发节点开始: model={model}, size={image_size}, ratio={aspect_ratio}, "
            f"scope={generate_scope}, ref_image_count={len(image_urls)}"
        )

        try:
            result = _run_three_view_jobs(
                api_key=resolved_key,
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                image_urls=image_urls,
                prompts=prompts,
                labels_prefix="普通三方案并发节点-",
                generate_scope=generate_scope,
                cache_key=f"normal_three_view:{unique_id}",
                auto_retry_until_success=auto_retry_until_success,
                max_retry_per_view=max_retry_per_view,
                retry_interval_sec=retry_interval_sec,
            )
        except Exception as e:
            msg = str(e)[:2500]
            logger.error(f"普通三方案并发节点生成失败: {msg}")
            img = _error_img("普通三方案并发节点生成失败")
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")

        elapsed = time.time() - start
        ordered = result["ordered"]
        lines = [
            f"✅ 普通三方案并发节点完成，耗时 {elapsed:.1f}s",
            "node_id: HrioBananaNormalThreeViewConcurrentNodeV330",
            "node_name: 🎨 Hrio｜普通三方案并发",
            f"model: {model}",
            f"image_size: {image_size}",
            f"aspect_ratio: {aspect_ratio}",
            f"generate_scope: {result.get('generate_scope')}",
            f"auto_retry_until_success: {result.get('auto_retry_until_success')}",
            f"max_retry_per_view: {result.get('max_retry_per_view')}",
            f"retry_interval_sec: {result.get('retry_interval_sec')}",
            f"cache_key: {result.get('cache_key')}",
            f"ref_image_count: {len(image_urls)}",
            "输出接口: front_image=方案A, side_image=方案B, back_image=方案C, images=三张批量合集",
            "输出顺序: images[0]=方案A, images[1]=方案B, images[2]=方案C",
        ]
        for idx, item in enumerate(ordered, start=1):
            lines.append(
                f"{idx}. {item.get('label', '')} | 耗时 {float(item.get('elapsed') or 0):.1f}s | seed={item.get('seed', '')} | "
                f"size={item.get('image_size', '')} | ratio={item.get('aspect_ratio', '')}"
            )
            if str(item.get("info") or "").strip():
                lines.append(str(item["info"]))

        summary = "\n".join(lines)
        logger.summary("普通三方案并发节点完成", {
            "节点ID": "HrioBananaNormalThreeViewConcurrentNodeV330",
            "节点名": "🎨 Hrio｜普通三方案并发",
            "输出": "正面/侧面/背面 + batch",
            "耗时": f"{elapsed:.1f}s",
            "模型": model,
            "尺寸": image_size,
            "宽高比": aspect_ratio,
            "生成范围": result.get("generate_scope"),
            "缓存Key": result.get("cache_key"),
            "失败视图": ",".join((result.get("errors_by_key") or {}).keys()) or "无",
            "ref_image_count": len(image_urls),
        })
        return _return_images_with_ui_preview((result["front"], result["side"], result["back"], result["batch"], summary, ""), label="banana_normal_three_view")

    def generate_automation(
        self,
        *,
        resolved_key: str,
        front_prompt: str,
        side_prompt: str,
        back_prompt: str,
        model: str,
        image_size: str,
        aspect_ratio: str,
        auto_retry_until_success: bool,
        max_retry_per_view: int,
        retry_interval_sec: float,
        generate_scope: str = "全部并发生成",
        global_prompt: str = "",
        negative_prompt: str = "",
        automation_payload: str = "",
        unique_id=None,
    ):
        start = time.time()
        cfg = _auto_normalize_payload(automation_payload, save_images_default=True, save_video_default=False)
        run_cache_key = f"normal_three_view_automation:{unique_id}"
        if not cfg.get("input_roots") and not cfg.get("preview_groups"):
            msg = "自动化已启用，但没有 input_roots / preview_groups。请在自动化面板选择输入根目录，或粘贴包含 preview_groups 的自动化 JSON。"
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")
        groups = _build_automation_sequence_groups_from_cfg(cfg)
        all_group_count = len(groups)
        run_sequences = set(str(x) for x in (cfg.get("run_sequences") or []) if str(x).strip())
        if run_sequences:
            groups = [g for g in groups if str(g.get("sequence") or "") in run_sequences]
        if not groups:
            if run_sequences:
                msg = f"自动化没有找到指定序号组：{', '.join(sorted(run_sequences))}。"
                img = _error_img(msg)
                return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")
            msg = "自动化没有扫描到任何有效序号组。"
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")

        # 自动化模式下同样使用三个独立方案提示词；不拼接共同提示词/限定词/负面词。
        prompts = {
            "front": _compose_manual_prompt(global_prompt, front_prompt, negative_prompt),
            "side": _compose_manual_prompt(global_prompt, side_prompt, negative_prompt),
            "back": _compose_manual_prompt(global_prompt, back_prompt, negative_prompt),
        }

        group_concurrency = int(cfg.get("group_concurrency") or 3)
        run_cache_key = f"normal_three_view_automation:{unique_id or int(time.time() * 1000)}"
        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(10, group_concurrency))) as executor:
            futures = [executor.submit(
                _run_three_view_automation_group,
                group=group,
                cfg=cfg,
                api_key=resolved_key,
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                prompts=prompts,
                labels="普通三方案并发节点",
                cache_key=run_cache_key,
                auto_retry_until_success=auto_retry_until_success,
                max_retry_per_view=max_retry_per_view,
                retry_interval_sec=retry_interval_sec,
                generate_scope=generate_scope,
            ) for group in groups]
            for future in as_completed(futures):
                results.append(future.result())

        results.sort(key=lambda x: _auto_sequence_sort_key(str(x.get("sequence") or "")))
        ok_results = [r for r in results if r.get("ok")]
        fail_results = [r for r in results if not r.get("ok")]
        elapsed = time.time() - start

        representative = ok_results[-1] if ok_results else None
        if representative:
            front = representative.get("front")
            side = representative.get("side")
            back = representative.get("back")
            batch = representative.get("batch")
            if batch is None:
                batch = _cat_image_batches_safe([front, side, back])
        else:
            front = side = back = batch = _error_img("自动化全部失败")

        lines = [
            f"✅ 普通三方案并发节点自动化批处理完成，耗时 {elapsed:.1f}s",
            f"model: {model}",
            f"image_size: {image_size}",
            f"aspect_ratio: {aspect_ratio}",
            f"input_roots: {len(cfg.get('input_roots') or [])}",
            f"groups: {len(groups)} / all_groups: {all_group_count}",
            f"run_sequences: {', '.join(sorted(run_sequences)) if run_sequences else '全部'}",
            f"generate_scope: {generate_scope}",
            f"success: {len(ok_results)}",
            f"failed: {len(fail_results)}",
            f"group_concurrency: {group_concurrency}",
            f"max_images_per_group: {cfg.get('max_images_per_group')}",
            f"output_root: {cfg['output_root']}",
            "输入规则: 只扫描输入根目录下的直接图片文件，例如 input_root_01/001.png；输出目录规则: output_序号/run_01/，图片文件 front.png / side.png / back.png",
        ]
        for r in results:
            if r.get("ok"):
                lines.append(f"✅ {r.get('sequence')} -> {r.get('output_dir')} | 输入图片 {r.get('input_image_count')} 张")
            else:
                lines.append(f"❌ {r.get('sequence')} -> {r.get('output_dir')} | {r.get('error')}")

        summary = "\n".join(lines)
        return _return_images_with_ui_preview((front, side, back, batch, summary, ""), label="banana_normal_automation")


def _extract_video_urls_from_response(data: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    _walk_extract_video_urls(data, urls)

    out: List[str] = []
    seen = set()
    for url in urls:
        u = str(url or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _extract_operation_name(data: Dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""

    op = data.get("operation") or data.get("operationName") or data.get("operation_name")
    if isinstance(op, dict):
        name = op.get("name") or op.get("operation") or op.get("id")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(op, str) and op.strip():
        return op.strip()

    name = data.get("name")
    if isinstance(name, str) and name.strip() and (
        "operation" in name.lower() or "operations/" in name.lower() or data.get("done") is not None
    ):
        return name.strip()

    for key in ("metadata", "response"):
        value = data.get(key)
        if isinstance(value, dict):
            found = _extract_operation_name(value)
            if found:
                return found

    return ""


def _operation_is_done(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if bool(data.get("done")):
        return True
    status = str(data.get("status") or data.get("state") or "").lower()
    return status in {"done", "succeeded", "success", "completed", "finished"}


def _poll_video_operation(api_key: str, operation_name: str) -> Tuple[List[str], Dict[str, Any]]:
    poll_interval = _safe_float(_cfg_or_manifest("veo_poll_interval_sec", "8"), 8.0, 1.0, 60.0)
    poll_timeout = _safe_float(_cfg_or_manifest("veo_poll_timeout_sec", "1800"), 1800.0, 30.0, 7200.0)
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }

    started = time.time()
    last_payload: Dict[str, Any] = {}

    while True:
        if time.time() - started > poll_timeout:
            raise RuntimeError(f"视频生成轮询超时：{operation_name}")

        _, payload, _, _ = _request_json_with_failover(
            "GET",
            _operation_get_url,
            builder_args=(operation_name,),
            headers=headers,
            json_payload=None,
            timeout=_cfg_int("read_timeout_sec", _TIMEOUT_IMAGE),
            action_name=f"视频生成轮询 {operation_name}",
        )
        last_payload = payload if isinstance(payload, dict) else {"raw": payload}
        urls = _extract_video_urls_from_response(last_payload)
        if urls:
            return urls, last_payload

        if _operation_is_done(last_payload):
            err = last_payload.get("error") if isinstance(last_payload, dict) else None
            if err:
                raise RuntimeError(f"视频生成失败：{err}")
            raise RuntimeError(f"视频生成已完成，但响应中未找到 mp4/mov/webm 地址：{json.dumps(last_payload, ensure_ascii=False)[:2000]}")

        logger.info(f"视频仍在生成，{poll_interval:.1f}s 后继续轮询: {operation_name}")
        time.sleep(poll_interval)


def _build_video_payloads(
    prompt: str,
    image_urls: List[str] | None = None,
    video_resolution: Any = None,
    aspect_ratio: Any = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Veo 只走 predictLongRunning。

    修复点：
    1. 不再先打 generateContent，避免必然 400：Veo models support predictLongRunning。
    2. UI 的 720p 会在 _normalize_video_resolution() 中兼容成后端合法的 720p。
    3. 参考图按当前后端 veo_protocol.py 能识别的字段发送：
       - 第一张作为 instances[0].image
       - 后面最多 3 张作为 parameters.referenceImages
       因为当前后端限制 referenceImages supports up to 3 images，所以插件侧直接截断，后端不需要做兼容。
    """
    resolution = _normalize_video_resolution(video_resolution or _cfg_or_manifest("veo_resolution", "1080p"))
    aspect_actual = _normalize_video_aspect_ratio(aspect_ratio or _cfg_or_manifest("veo_aspect_ratio", "16:9"))
    duration = _safe_int(_cfg_or_manifest("veo_duration_seconds", "8"), 8, 1, 60)
    count = _safe_int(_cfg_or_manifest("veo_number_of_videos", "1"), 1, 1, 4)

    # 1080p / 720p 图生视频统一 8 秒，和后端校验保持一致。
    if resolution in {"1080p", "720p", "4k"}:
        duration = 8

    text = str(prompt or "").strip()
    # 当前后端只支持：instances[0].image + parameters.referenceImages 最多 3 张。
    # 所以视频节点最多发送 4 张参考图，避免后端返回 referenceImages supports up to 3 images。
    refs = [str(u or "").strip() for u in (image_urls or []) if str(u or "").strip()][:4]

    media_items: List[Dict[str, Any]] = []
    for u in refs:
        media_items.append({
            "uri": u,
            "fileUri": u,
            "mimeType": _guess_mime_from_url(u, "image/png"),
        })

    instance: Dict[str, Any] = {"prompt": text}
    if media_items:
        instance["image"] = media_items[0]

    parameters: Dict[str, Any] = {
        "resolution": resolution,
        "video_resolution": resolution,
        "aspectRatio": aspect_actual,
        "aspect_ratio": aspect_actual,
        "durationSeconds": duration,
        "sampleCount": count,
        "numberOfVideos": count,
        "storage": "oss",
    }
    if len(media_items) > 1:
        parameters["referenceImages"] = media_items[1:]

    return [
        (
            "predictLongRunning",
            {
                "instances": [instance],
                "parameters": parameters,
                "enable_oss": True,
                "image_size": resolution,
                "video_resolution": resolution,
                "aspect_ratio": aspect_actual,
            },
        )
    ]

def _generate_video_from_prompt(
    api_key: str,
    prompt: str,
    video_model: str,
    image_urls: List[str] | None = None,
    video_resolution: Any = None,
    aspect_ratio: Any = None,
) -> Dict[str, Any]:
    resolved_key = str(api_key or "").strip() or _cfg("api_key", "")
    if not resolved_key:
        raise RuntimeError("请在节点中填入 API Key，或在 config.ini 的 [banana] 下配置 api_key")

    text = str(prompt or "").strip()
    if not text:
        raise RuntimeError("请填写视频提示词")

    refs = [str(u or "").strip() for u in (image_urls or []) if str(u or "").strip()][:4]

    display_model = str(video_model or _manual_video_model_default()).strip()
    actual_model = _MODEL_DISPLAY_TO_ACTUAL.get(display_model, display_model)
    if not actual_model:
        actual_model = "veo3.1"

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": resolved_key,
    }

    last_error: Exception | None = None
    raw_payload: Dict[str, Any] = {}

    resolved_video_resolution = _normalize_video_resolution(video_resolution or _cfg_or_manifest("veo_resolution", "1080p"))
    resolved_aspect_ratio = _normalize_video_aspect_ratio(aspect_ratio or _cfg_or_manifest("veo_aspect_ratio", "16:9"))

    for action, payload in _build_video_payloads(text, refs, resolved_video_resolution, resolved_aspect_ratio):
        try:
            logger.info(
                f"生视频节点请求: model={actual_model}, action={action}, resolution={resolved_video_resolution}, "
                f"aspect_ratio={resolved_aspect_ratio}, enable_oss=True, ref_image_count={len(refs)}"
            )
            _, data, route_name, used_url = _request_json_with_failover(
                "POST",
                _video_generate_url,
                builder_args=(actual_model,),
                builder_kwargs={"action": action, "enable_oss": True},
                headers=headers,
                json_payload=payload,
                timeout=_cfg_int("read_timeout_sec", _TIMEOUT_IMAGE),
                action_name=f"AI 生视频 {actual_model}:{action}",
            )

            raw_payload = data if isinstance(data, dict) else {"raw": data}
            urls = _extract_video_urls_from_response(raw_payload)
            if urls:
                return {
                    "ok": True,
                    "model": actual_model,
                    "display_model": display_model,
                    "action": action,
                    "route": route_name,
                    "url": used_url,
                    "mp4url": urls[0],
                    "all_urls": urls,
                    "raw": raw_payload,
                    "ref_image_count": len(refs),
                    "video_resolution": resolved_video_resolution,
                    "aspect_ratio": resolved_aspect_ratio,
                }

            op_name = _extract_operation_name(raw_payload)
            if op_name:
                urls, final_payload = _poll_video_operation(resolved_key, op_name)
                return {
                    "ok": True,
                    "model": actual_model,
                    "display_model": display_model,
                    "action": action,
                    "route": route_name,
                    "url": used_url,
                    "operation": op_name,
                    "mp4url": urls[0],
                    "all_urls": urls,
                    "raw": final_payload,
                    "ref_image_count": len(refs),
                    "video_resolution": resolved_video_resolution,
                    "aspect_ratio": resolved_aspect_ratio,
                }

            raise RuntimeError(f"视频接口未返回 mp4 地址或 operation：{json.dumps(raw_payload, ensure_ascii=False)[:2000]}")

        except Exception as e:
            last_error = e
            logger.warning(f"生视频 action={action} 失败，尝试下一种接口格式: {e}")
            continue

    if last_error:
        raise last_error
    raise RuntimeError("视频生成失败：没有可用的视频接口格式")


class HrioBananaNormalSingleImageNode:
    """普通分类里的单输出图片节点：只输出 1 个 IMAGE。"""

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = "HRIO设计/普通"

    @classmethod
    def INPUT_TYPES(cls):
        model_options = _enum_source_options("model_map", ["banano2", "banano-pro", "gemini3.1-pro"])
        image_size_options = _enum_source_options("image_size_options", ["1K", "2K", "4K", "8K（默认16:9）"])
        aspect_options = _enum_source_options(
            "aspect_ratio_options",
            ["Auto", "1:1 (方形)", "3:4 (竖屏标准)", "9:16 (竖屏/手机)", "16:9 (横屏宽幅)"],
        )

        default_model = _manual_model_default()
        if default_model not in model_options:
            default_model = model_options[0]

        default_size = _manual_image_size_default()
        if default_size not in image_size_options:
            default_size = image_size_options[0]

        default_ratio = _manual_aspect_ratio_default("Auto")
        if default_ratio not in aspect_options:
            default_ratio = aspect_options[0]

        optional = {
            "automation_payload": _automation_payload_widget(),
        }

        slot_count = int(_NODE.get("optional_image_slots", 10) or 10)
        slot_count = max(1, min(10, slot_count))
        for i in range(1, slot_count + 1):
            optional[f"image_{i}"] = (
                "IMAGE",
                {
                    "tooltip": f"参考图 {i}；会上传后和提示词一起发送给图片生成接口。",
                },
            )

        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "default": "高审美设计提案图，适合平面设计或室内设计方向。画面构图高级、层级清晰、材质自然、光影干净、真实可落地；可根据参考图生成品牌视觉、海报、网页首屏、室内空间、材质情绪板或软装方案。",
                        "multiline": True,
                        "tooltip": "单图提示词。此节点只输出一张 IMAGE。",
                    },
                ),
                "model": (
                    model_options,
                    {
                        "default": default_model,
                        "tooltip": "图片模型。",
                    },
                ),
                "api_key": (
                    "STRING",
                    {
                        "default": _cfg("api_key", ""),
                        "multiline": False,
                        "tooltip": "填入 API Key；留空时尝试读取 config.ini 的 api_key。",
                    },
                ),
                "image_size": (
                    image_size_options,
                    {
                        "default": default_size,
                        "tooltip": "图片尺寸。",
                    },
                ),
                "aspect_ratio": (
                    aspect_options,
                    {
                        "default": default_ratio,
                        "tooltip": "图片宽高比。",
                    },
                ),
            },
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID", "prompt_graph": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    def generate(
        self,
        prompt: str,
        model: str,
        api_key: str = "",
        image_size: str = "2K",
        aspect_ratio: str = "Auto",
        negative_prompt: str = "",
        automation_payload: str = "",
        unique_id=None,
        prompt_graph=None,
        extra_pnginfo=None,
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")
        automation_payload = _resolve_automation_payload(
            automation_payload,
            unique_id=unique_id,
            prompt=prompt_graph,
            extra_pnginfo=extra_pnginfo,
            values=kwargs,
        )

        if not resolved_key:
            msg = "请在节点中填入 API Key，或在 config.ini 的 [banana] 下配置 api_key"
            logger.error(msg)
            return _return_images_with_ui_preview((_error_img(msg),), label="banana_normal_single_error")

        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            msg = "请填写单图提示词"
            logger.error(msg)
            return _return_images_with_ui_preview((_error_img(msg),), label="banana_normal_single_error")

        if _automation_enabled(automation_payload):
            return self.generate_automation(
                resolved_key=resolved_key,
                prompt=prompt,
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                negative_prompt=negative_prompt,
                automation_payload=automation_payload,
                unique_id=unique_id,
            )

        final_prompt = _compose_single_image_prompt(prompt, negative_prompt)

        try:
            image_urls = _upload_reference_images_for_node(kwargs, resolved_key)
            item = _single_image_generation_job(
                "普通单图节点",
                _node_base_values(
                    resolved_key,
                    final_prompt,
                    model,
                    image_size,
                    aspect_ratio,
                    auto_retry_until_success=True,
                    max_retry_per_view=_safe_int(_cfg_or_manifest("max_retry_per_view", "6"), 6, 1, 999),
                    retry_interval_sec=_safe_float(_cfg_or_manifest("retry_interval_sec", "1.5"), 1.5, 0.1, 30.0),
                ),
                image_urls,
            )
            elapsed = time.time() - start
            logger.summary("普通单图节点完成", {
                "节点ID": "HrioBananaNormalSingleImageNode",
                "节点名": "🎨 Hrio｜普通单图生成",
                "模型": item.get("display_model") or model,
                "尺寸": item.get("image_size") or image_size,
                "宽高比": item.get("aspect_ratio") or aspect_ratio,
                "耗时": f"{elapsed:.1f}s",
                "ref_image_count": len(image_urls),
                "seed": item.get("seed"),
            })
            image_out = item.get("tensor")
            if image_out is None:
                image_out = _error_img("普通单图节点没有返回图片")
            _publish_single_image_runtime_result(
                cache_key=f"normal_single_image_manual:{unique_id or 'default'}",
                label="普通单图节点",
                model=str(item.get("display_model") or item.get("model") or model),
                image_size=str(item.get("image_size") or image_size),
                aspect_ratio=str(item.get("aspect_ratio") or aspect_ratio),
                tensor=image_out,
            )
            return _return_images_with_ui_preview((image_out,), label="banana_normal_single_image")
        except Exception as e:
            msg = str(e)[:2500]
            logger.error(f"普通单图节点生成失败: {msg}")
            _publish_single_image_runtime_result(
                cache_key=f"normal_single_image_manual:{unique_id or 'default'}",
                label="普通单图节点",
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                tensor=None,
                error=msg,
            )
            return _return_images_with_ui_preview((_error_img(f"普通单图节点生成失败：{msg[:220]}"),), label="banana_normal_single_error")


    def generate_automation(
        self,
        *,
        resolved_key: str,
        prompt: str,
        model: str,
        image_size: str = "2K",
        aspect_ratio: str = "Auto",
        negative_prompt: str = "",
        automation_payload: str = "",
        unique_id=None,
    ):
        start = time.time()
        cfg = _auto_normalize_payload(automation_payload, save_images_default=True, save_video_default=False)
        if not cfg.get("input_roots") and not cfg.get("preview_groups"):
            return _return_images_with_ui_preview((_error_img("普通单图自动化失败：没有 input_roots / preview_groups"),), label="banana_normal_single_automation_error")

        groups = _build_automation_sequence_groups_from_cfg(cfg)
        all_group_count = len(groups)
        run_sequences = set(str(x) for x in (cfg.get("run_sequences") or []) if str(x).strip())
        if run_sequences:
            groups = [g for g in groups if str(g.get("sequence") or "") in run_sequences]
        if not groups:
            msg = f"普通单图自动化没有找到指定序号组：{', '.join(sorted(run_sequences))}" if run_sequences else "普通单图自动化没有扫描到任何有效序号组"
            return _return_images_with_ui_preview((_error_img(msg),), label="banana_normal_single_automation_error")

        group_concurrency = int(cfg.get("group_concurrency") or 3)
        run_cache_key = f"normal_single_image_automation:{unique_id or int(time.time() * 1000)}"
        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(10, group_concurrency))) as executor:
            futures = [
                executor.submit(
                    _run_single_image_automation_group,
                    group=group,
                    cfg=cfg,
                    api_key=resolved_key,
                    prompt=prompt,
                    model=model,
                    image_size=image_size,
                    aspect_ratio=aspect_ratio,
                    negative_prompt=negative_prompt,
                    cache_key=run_cache_key,
                )
                for group in groups
            ]
            for future in as_completed(futures):
                results.append(future.result())

        results.sort(key=lambda x: _auto_sequence_sort_key(str(x.get("sequence") or "")))
        ok_results = [r for r in results if r.get("ok")]
        fail_results = [r for r in results if not r.get("ok")]
        elapsed = time.time() - start
        # 收集全部成功组的输出图片路径（供媒体资产面板入库）
        all_output_paths: List[str] = []
        for r in ok_results:
            p = str(r.get("local_image_path") or "").strip()
            if p and os.path.isfile(p):
                all_output_paths.append(p)
 
        last_ok = ok_results[-1] if ok_results else {}
        image_out = last_ok.get("image") if isinstance(last_ok, dict) else None
        if image_out is None:
            image_out = _error_img("普通单图自动化没有成功图片")
 
        logger.summary("普通单图自动化完成", {
            "模型": model,
            "耗时": f"{elapsed:.1f}s",
            "input_roots": len(cfg.get("input_roots") or []),
            "groups": f"{len(groups)} / {all_group_count}",
            "success": len(ok_results),
            "failed": len(fail_results),
            "output_paths": len(all_output_paths),
            "output_root": cfg["output_root"],
        })
        return _return_images_with_ui_preview(
            (image_out,),
            label="banana_normal_single_automation",
            extra_output_paths=all_output_paths,   # ← 全部图进媒体资产
        )

class HrioBananaNormalVideoSingleOutputNode:
    """普通分类里的单输出视频节点：只输出 1 个 STRING，本地可预览视频路径。"""

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video",)
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = "HRIO设计/普通"

    @classmethod
    def INPUT_TYPES(cls):
        video_models = _video_model_options()
        default_model = _manual_video_model_default()
        if default_model not in video_models:
            default_model = video_models[0]

        video_resolution_options = _video_resolution_options()
        default_video_resolution = _manual_video_resolution_default()
        if default_video_resolution not in video_resolution_options:
            default_video_resolution = video_resolution_options[0]

        video_aspect_options = _video_aspect_ratio_options()
        default_video_aspect = _manual_video_aspect_ratio_default()
        if default_video_aspect not in video_aspect_options:
            default_video_aspect = video_aspect_options[0]

        optional = {
            "automation_payload": _automation_payload_widget(),
        }
        slot_count = int(_NODE.get("optional_image_slots", 10) or 10)
        slot_count = max(1, min(10, slot_count))
        for i in range(1, slot_count + 1):
            optional[f"image_{i}"] = (
                "IMAGE",
                {
                    "tooltip": f"视频参考图 {i}；当前后端实际最多发送 4 张：第 1 张 image，后 3 张 referenceImages。",
                },
            )

        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "default": "一段高审美设计方案展示视频，适合平面设计或室内设计提案。镜头稳定、运动克制、光影自然、材质细节清晰，展示设计氛围、空间层次、版式节奏或品牌视觉延展。",
                        "multiline": True,
                        "tooltip": "视频提示词。此节点只输出一个 video 字符串，本地路径可直接预览。",
                    },
                ),
                "video_model": (
                    video_models,
                    {
                        "default": default_model,
                        "tooltip": "视频模型。默认会使用 veo3.1 或 manifest/config 中配置的视频模型。",
                    },
                ),
                "api_key": (
                    "STRING",
                    {
                        "default": _cfg("api_key", ""),
                        "multiline": False,
                        "tooltip": "填入 API Key；留空时尝试读取 config.ini 的 api_key。",
                    },
                ),
                "video_resolution": (
                    video_resolution_options,
                    {
                        "default": default_video_resolution,
                        "tooltip": "视频分辨率，会随 JSON 一起发送给后端。",
                    },
                ),
                "aspect_ratio": (
                    video_aspect_options,
                    {
                        "default": default_video_aspect,
                        "tooltip": "横屏 16:9 或竖屏 9:16，会随 JSON 一起发送给后端。",
                    },
                ),
            },
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID", "prompt_graph": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    def generate(
        self,
        prompt: str,
        video_model: str,
        api_key: str = "",
        video_resolution: str = "1080p",
        aspect_ratio: str = "16:9 (横屏宽幅)",
        automation_payload: str = "",
        unique_id=None,
        prompt_graph=None,
        extra_pnginfo=None,
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")
        automation_payload = _resolve_automation_payload(
            automation_payload,
            unique_id=unique_id,
            prompt=prompt_graph,
            extra_pnginfo=extra_pnginfo,
            values=kwargs,
        )

        if not resolved_key:
            msg = "请在节点中填入 API Key，或在 config.ini 的 [banana] 下配置 api_key"
            logger.error(msg)
            return _return_video_with_ui_preview(("",), "", label="banana_normal_video_single_error")

        if _automation_enabled(automation_payload):
            return self.generate_automation(
                resolved_key=resolved_key,
                prompt=prompt,
                video_model=video_model,
                video_resolution=video_resolution,
                aspect_ratio=aspect_ratio,
                automation_payload=automation_payload,
            )

        try:
            image_urls = _upload_reference_images_for_node(kwargs, resolved_key)
            result = _generate_video_from_prompt(
                resolved_key,
                prompt,
                video_model,
                image_urls=image_urls,
                video_resolution=video_resolution,
                aspect_ratio=aspect_ratio,
            )
            elapsed = time.time() - start
            mp4url = str(result.get("mp4url") or "")
            logger.summary("普通单输出视频节点完成", {
                "节点ID": "HrioBananaNormalVideoSingleOutputNode",
                "节点名": "🎨 Hrio｜普通生视频（单输出）",
                "模型": f"{result.get('display_model')} / {result.get('model')}",
                "耗时": f"{elapsed:.1f}s",
                "video_resolution": result.get("video_resolution") or _normalize_video_resolution(video_resolution),
                "aspect_ratio": result.get("aspect_ratio") or _normalize_video_aspect_ratio(aspect_ratio),
                "ref_image_count": result.get("ref_image_count") or 0,
                "mp4url": mp4url,
            })
            # 单输出：保存到 ComfyUI temp 后，把唯一 STRING 输出替换成本地可预览路径。
            return _return_video_with_ui_preview((mp4url,), mp4url, label="banana_normal_video_single")
        except Exception as e:
            msg = str(e)[:3000]
            logger.error(f"普通单输出视频节点失败: {msg}")
            return _return_video_with_ui_preview(("",), "", label="banana_normal_video_single_error")


    def generate_automation(
        self,
        *,
        resolved_key: str,
        prompt: str,
        video_model: str,
        video_resolution: str = "1080p",
        aspect_ratio: str = "16:9 (横屏宽幅)",
        automation_payload: str = "",
    ):
        batch = _run_video_automation_batch(
            resolved_key=resolved_key,
            prompt=prompt,
            video_model=video_model,
            video_resolution=video_resolution,
            aspect_ratio=aspect_ratio,
            automation_payload=automation_payload,
            output_kind="normal_video_single",
        )
        if not batch.get("ok"):
            return _return_video_with_ui_preview(("",), "", label="banana_normal_video_single_automation_error")
        video_path = str(batch.get("local_video_path") or batch.get("mp4url") or "")
        return _return_video_with_ui_preview((video_path,), video_path, label="banana_normal_video_single_automation")


class HrioBananaPromptVideoNode:
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("info", "video", "mp4url")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = "HRIO设计/视频生成"

    @classmethod
    def INPUT_TYPES(cls):
        video_models = _video_model_options()
        default_model = _manual_video_model_default()
        if default_model not in video_models:
            default_model = video_models[0]

        video_resolution_options = _video_resolution_options()
        default_video_resolution = _manual_video_resolution_default()
        if default_video_resolution not in video_resolution_options:
            default_video_resolution = video_resolution_options[0]

        video_aspect_options = _video_aspect_ratio_options()
        default_video_aspect = _manual_video_aspect_ratio_default()
        if default_video_aspect not in video_aspect_options:
            default_video_aspect = video_aspect_options[0]

        optional = {
            "automation_payload": _automation_payload_widget(),
        }

        slot_count = int(_NODE.get("optional_image_slots", 10) or 10)
        slot_count = max(1, min(10, slot_count))
        for i in range(1, slot_count + 1):
            optional[f"image_{i}"] = (
                "IMAGE",
                {
                    "tooltip": f"视频参考图 {i}；生视频节点支持最多 10 张输入图。",
                },
            )

        # 注意顺序：prompt / video_model 放在 api_key 前面，避免旧工作流因为新增 API Key 导致提示词和模型错位。
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {
                        "default": "一段高审美设计方案展示视频，适合平面设计或室内设计提案。镜头稳定、运动克制、光影自然、材质细节清晰，展示设计氛围、空间层次、版式节奏或品牌视觉延展。",
                        "multiline": True,
                        "tooltip": "视频提示词。",
                    },
                ),
                "video_model": (
                    video_models,
                    {
                        "default": default_model,
                        "tooltip": "视频模型。默认会使用 veo3.1 或 manifest/config 中配置的视频模型。",
                    },
                ),
                "api_key": (
                    "STRING",
                    {
                        "default": _cfg("api_key", ""),
                        "multiline": False,
                        "tooltip": "填入 API Key；留空时尝试读取 config.ini 的 api_key。",
                    },
                ),
                "video_resolution": (
                    video_resolution_options,
                    {
                        "default": default_video_resolution,
                        "tooltip": "视频分辨率，会随提示词 JSON 一起发送给后端。",
                    },
                ),
                "aspect_ratio": (
                    video_aspect_options,
                    {
                        "default": default_video_aspect,
                        "tooltip": "视频画面比例：横屏 16:9 或竖屏 9:16，会随提示词 JSON 一起发送给后端。",
                    },
                ),
            },
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID", "prompt_graph": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    def generate(
        self,
        prompt: str,
        video_model: str,
        api_key: str = "",
        video_resolution: str = "1080p",
        aspect_ratio: str = "16:9 (横屏宽幅)",
        automation_payload: str = "",
        unique_id=None,
        prompt_graph=None,
        extra_pnginfo=None,
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")
        automation_payload = _resolve_automation_payload(
            automation_payload,
            unique_id=unique_id,
            prompt=prompt_graph,
            extra_pnginfo=extra_pnginfo,
            values=kwargs,
        )

        if not resolved_key:
            msg = "请在节点中填入 API Key，或在 config.ini 的 [banana] 下配置 api_key"
            logger.error(msg)
            return _return_video_with_ui_preview((f"❌ Hrio Design 生视频失败\n{msg}", "", ""), "", label="banana_video_error")
        if _automation_enabled(automation_payload):
            return self.generate_automation(
                resolved_key=resolved_key,
                prompt=prompt,
                video_model=video_model,
                video_resolution=video_resolution,
                aspect_ratio=aspect_ratio,
                automation_payload=automation_payload,
                unique_id=unique_id,
            )

        try:
            image_urls = _upload_reference_images_for_node(kwargs, resolved_key)
            result = _generate_video_from_prompt(
                resolved_key,
                prompt,
                video_model,
                image_urls=image_urls,
                video_resolution=video_resolution,
                aspect_ratio=aspect_ratio,
            )
            elapsed = time.time() - start
            mp4url = str(result.get("mp4url") or "")
            info = "\n".join([
                f"✅ Hrio Design 生视频完成，耗时 {elapsed:.1f}s",
                "node_id: HrioBananaPromptVideoNode",
                "node_name: 🎨 Hrio｜生视频",
                f"video_model: {result.get('display_model')} ({result.get('model')})",
                f"video_resolution: {result.get('video_resolution') or _normalize_video_resolution(video_resolution)}",
                f"aspect_ratio: {result.get('aspect_ratio') or _normalize_video_aspect_ratio(aspect_ratio)}",
                f"action: {result.get('action')}",
                f"operation: {result.get('operation') or ''}",
                "enable_oss: True",
                f"ref_image_count: {result.get('ref_image_count') or 0}",
                f"mp4url: {mp4url}",
                "说明：节点界面显示提示词、模型、API Key、视频分辨率、横竖屏比例和参考图；为匹配当前后端协议，视频最多发送 4 张参考图，其中第 1 张为 image，后 3 张为 referenceImages。",
            ])
            logger.summary("Hrio Design 生视频完成", {
                "模型": f"{result.get('display_model')} / {result.get('model')}",
                "耗时": f"{elapsed:.1f}s",
                "enable_oss": True,
                "ref_image_count": result.get("ref_image_count") or 0,
                "video_resolution": result.get("video_resolution") or _normalize_video_resolution(video_resolution),
                "aspect_ratio": result.get("aspect_ratio") or _normalize_video_aspect_ratio(aspect_ratio),
                "mp4url": mp4url,
            })
            return _return_video_with_ui_preview((info, mp4url, mp4url), mp4url, label="banana_video")
        except Exception as e:
            msg = str(e)[:3000]
            logger.error(f"Hrio Design 生视频失败: {msg}")
            return _return_video_with_ui_preview((f"❌ Hrio Design 生视频失败\n{msg}", "", ""), "", label="banana_video_error")

    def generate_automation(
        self,
        *,
        resolved_key: str,
        prompt: str,
        video_model: str,
        video_resolution: str = "1080p",
        aspect_ratio: str = "16:9 (横屏宽幅)",
        automation_payload: str = "",
        unique_id=None,
    ):
        start = time.time()
        cfg = _auto_normalize_payload(automation_payload, save_images_default=False, save_video_default=True)
        if not cfg.get("input_roots") and not cfg.get("preview_groups"):
            return _return_video_with_ui_preview(("❌ Hrio Design 生视频自动化失败\n自动化已启用，但没有 input_roots / preview_groups。", "", ""), "", label="banana_video_automation_error")
        groups = _build_automation_sequence_groups_from_cfg(cfg)
        all_group_count = len(groups)
        run_sequences = set(str(x) for x in (cfg.get("run_sequences") or []) if str(x).strip())
        if run_sequences:
            groups = [g for g in groups if str(g.get("sequence") or "") in run_sequences]
        if not groups:
            if run_sequences:
                return _return_video_with_ui_preview((f"❌ Hrio Design 生视频自动化失败\n自动化没有找到指定序号组：{', '.join(sorted(run_sequences))}。", "", ""), "", label="banana_video_automation_error")
            return _return_video_with_ui_preview(("❌ Hrio Design 生视频自动化失败\n自动化没有扫描到任何有效序号组。", "", ""), "", label="banana_video_automation_error")
        group_concurrency = int(cfg.get("group_concurrency") or 3)
        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(10, group_concurrency))) as executor:
            futures = [
                executor.submit(
                    _run_video_automation_group,
                    group=group,
                    cfg=cfg,
                    api_key=resolved_key,
                    prompt=prompt,
                    video_model=video_model,
                    video_resolution=video_resolution,
                    aspect_ratio=aspect_ratio,
                )
                for group in groups
            ]
            for future in as_completed(futures):
                results.append(future.result())

        results.sort(key=lambda x: _auto_sequence_sort_key(str(x.get("sequence") or "")))
        ok_results = [r for r in results if r.get("ok")]
        fail_results = [r for r in results if not r.get("ok")]
        elapsed = time.time() - start
        last_ok = (ok_results[-1] if ok_results else {})
        mp4url = str(last_ok.get("mp4url") or "")
        local_video_path = str(last_ok.get("local_video_path") or "")
        lines = [
            f"✅ Hrio Design 生视频自动化批处理完成，耗时 {elapsed:.1f}s",
            f"video_model: {video_model}",
            f"video_resolution: {_normalize_video_resolution(video_resolution)}",
            f"aspect_ratio: {_normalize_video_aspect_ratio(aspect_ratio)}",
            "enable_oss: True",
            f"input_roots: {len(cfg.get('input_roots') or [])}",
            f"groups: {len(groups)} / all_groups: {all_group_count}",
            f"run_sequences: {', '.join(sorted(run_sequences)) if run_sequences else '全部'}",
            f"success: {len(ok_results)}",
            f"failed: {len(fail_results)}",
            f"group_concurrency: {group_concurrency}",
            f"max_images_per_group: {cfg.get('max_images_per_group')}",
            f"output_root: {cfg['output_root']}",
            "输入规则: 只扫描输入根目录下的直接图片文件，例如 input_root_01/001.png；输出目录规则: output_序号/run_01/，视频文件 result.mp4。",
        ]
        for r in results:
            if r.get("ok"):
                lines.append(f"✅ {r.get('sequence')} -> {r.get('output_dir')} | 输入图片 {r.get('input_image_count')} 张 | mp4={r.get('mp4url')}")
            else:
                lines.append(f"❌ {r.get('sequence')} -> {r.get('output_dir')} | {r.get('error')}")
        return _return_video_with_ui_preview(("\n".join(lines), local_video_path or mp4url, mp4url), local_video_path or mp4url, label="banana_video_automation")


NODE_CLASS_MAPPINGS = {
    "HrioBananaNormalThreeViewConcurrentNodeV330": HrioBananaNormalThreeViewConcurrentNodeV330,
    "HrioBananaNormalSingleImageNode": HrioBananaNormalSingleImageNode,
    "HrioBananaNormalVideoSingleOutputNode": HrioBananaNormalVideoSingleOutputNode,
    "HrioBananaPromptVideoNode": HrioBananaPromptVideoNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HrioBananaNormalThreeViewConcurrentNodeV330": "🎨 Hrio Design｜三方案并发",
    "HrioBananaNormalSingleImageNode": "🎨 Hrio Design｜单图生成",
    "HrioBananaNormalVideoSingleOutputNode": "🎨 Hrio Design｜单视频生成",
    "HrioBananaPromptVideoNode": "🎨 Hrio Design｜视频生成",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "HrioBananaNormalThreeViewConcurrentNodeV330",
    "HrioBananaNormalSingleImageNode",
    "HrioBananaNormalVideoSingleOutputNode",
    "HrioBananaPromptVideoNode",
    "logger",
    "_MANIFEST",
    "_NODE",
    "_cfg",
    "_cfg_or_manifest",
    "_enum_source_options",
    "_enum_source_display",
    "_manual_model_default",
    "_manual_image_size_default",
    "_manual_aspect_ratio_default",
    "_manual_video_resolution_default",
    "_manual_video_aspect_ratio_default",
    "_video_resolution_options",
    "_video_aspect_ratio_options",
    "_normalize_video_resolution",
    "_normalize_video_aspect_ratio",
    "_return_images_with_ui_preview",
    "_return_video_with_ui_preview",
    "_upload_reference_images_for_node",
    "_single_image_generation_job",
    "_node_base_values",
    "_cat_image_batches_safe",
    "_error_img",
    "_HAS_PROMPT_SERVER",
    "PromptServer",
    "aiohttp_web",
    "_run_three_view_jobs",
    "_THREE_VIEW_SCOPE_OPTIONS",
    "_runtime_results_payload",
    "_clear_runtime_results",
    "_resolve_automation_payload",
]

def _register_hrio_routes() -> None:
    """
    向 ComfyUI PromptServer 注册 Hrio Design 所需的后端路由。
 
    前端 JS 使用的路由（见 banana_triple_view_ui.js 顶部常量）：
      GET  /hrio-design/runtime          ← 历史弹窗 & 最近生成面板轮询
      POST /hrio-design/runtime/clear    ← 清理历史按钮
      GET  /hrio-design/config           ← 配置读取（可选，兜底返回空对象）
      POST /hrio-design/automation/select-folder   ← 自动化选文件夹
      POST /hrio-design/automation/preview         ← 自动化预览扫描
 
    所有路由必须在这里注册，否则 404 → 前端永远卡在"正在读取生成历史…"状态。
    """
    if not _HAS_PROMPT_SERVER or PromptServer is None or aiohttp_web is None:
        logger.warning(
            "[Hrio Design] PromptServer / aiohttp 不可用，跳过路由注册；"
            "历史面板将无法正常工作。"
        )
        return
 
    try:
        server = PromptServer.instance
    except Exception:
        logger.warning("[Hrio Design] 无法获取 PromptServer.instance，跳过路由注册。")
        return
 
    # ── GET /hrio-design/runtime ────────────────────────────────────────────
    async def handle_runtime(request):
        try:
            payload = _runtime_results_payload()
            return aiohttp_web.Response(
                content_type="application/json",
                text=json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:
            logger.error(f"[/hrio-design/runtime] 处理失败: {exc}")
            return aiohttp_web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            )
 
    # ── POST /hrio-design/runtime/clear ─────────────────────────────────────
    async def handle_runtime_clear(request):
        try:
            result = _clear_runtime_results()
            return aiohttp_web.Response(
                content_type="application/json",
                text=json.dumps(result, ensure_ascii=False),
            )
        except Exception as exc:
            logger.error(f"[/hrio-design/runtime/clear] 处理失败: {exc}")
            return aiohttp_web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            )
 
    # ── GET /hrio-design/config ──────────────────────────────────────────────
    async def handle_config(request):
        try:
            cfg_out = {
                "ok": True,
                "version": "8.2.3",
                "base_url": _primary_base_url(),
                "fallback_base_url": _fallback_base_url(),
                "model": _cfg_or_manifest("model", "banano"),
                "image_size": _cfg_or_manifest("image_size", "2K"),
                "aspect_ratio": _cfg_or_manifest("aspect_ratio", "Auto"),
            }
            return aiohttp_web.Response(
                content_type="application/json",
                text=json.dumps(cfg_out, ensure_ascii=False),
            )
        except Exception as exc:
            return aiohttp_web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            )
 
    async def handle_automation_select_folder(request):
        """
        弹出系统文件夹选择对话框，返回用户选中的路径。

        兼容策略（按优先级）：
        1. tkinter.filedialog — 跨平台，ComfyUI 标准环境可用
        2. 读取 POST body 里的 path 字段 — 用户手动粘贴路径时的降级方案
        """
        selected_path = ""
        error_msg = ""

        # ── 优先尝试 tkinter 文件夹对话框 ───────────────────────────────────
        try:
            import tkinter as tk
            from tkinter import filedialog

            def _pick():
                root_win = tk.Tk()
                root_win.withdraw()
                root_win.attributes("-topmost", True)
                path = filedialog.askdirectory(
                    title="选择输入根目录（Hrio Design 自动化）",
                    parent=root_win,
                )
                root_win.destroy()
                return str(path or "").strip()

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_pick)
                selected_path = fut.result(timeout=120)

        except Exception as tk_err:
            error_msg = str(tk_err)
            logger.warning(f"[/hrio-design/automation/select-folder] tkinter 不可用: {tk_err}")

        # ── 降级：读取 POST body 里的 path 字段 ─────────────────────────────
        if not selected_path:
            try:
                body = await request.json()
                fallback = str(body.get("path") or body.get("folder") or "").strip().strip('"')
                if fallback and os.path.isdir(fallback):
                    selected_path = fallback
            except Exception:
                pass

        if not selected_path:
            return aiohttp_web.Response(
                status=400,
                content_type="application/json",
                text=json.dumps(
                    {
                        "ok": False,
                        "path": "",
                        "error": error_msg or "未选择目录，或对话框不可用（headless 环境请手动填写路径）",
                    },
                    ensure_ascii=False,
                ),
            )

        return aiohttp_web.Response(
            content_type="application/json",
            text=json.dumps({"ok": True, "path": selected_path}, ensure_ascii=False),
        )
 
    async def handle_automation_preview(request):
        """
        接收完整 automation_payload JSON，实时扫描输入根目录，
        返回序号分组预览列表（含缩略图 base64）。
        前端自动化面板点击"预览分组"或添加目录后自动调用。
        """
        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            # ── 从 body 恢复配置 ───────────────────────────────────────────
            input_roots = _auto_clean_path_list(
                body.get("input_roots") or body.get("inputRoots") or [],
                10,
            )
            output_root = str(body.get("output_root") or body.get("outputRoot") or "").strip()
            if not output_root:
                output_root = _default_automation_output_root()

            max_images_per_group = _safe_int(body.get("max_images_per_group", 10), 10, 1, 10)
            require_all = _value_as_bool(body.get("require_all_roots_present"), False)

            if not input_roots:
                return aiohttp_web.Response(
                    content_type="application/json",
                    text=json.dumps(
                        {
                            "ok": False,
                            "error": "没有 input_roots，请先添加输入根目录",
                            "groups": [],
                            "scan_reports": [],
                            "scan_summary": {},
                        },
                        ensure_ascii=False,
                    ),
                )

            # ── 扫描各根目录，收集扫描报告 ────────────────────────────────
            scan_reports: List[Dict[str, Any]] = []
            total_scanned = 0
            total_images = 0
            total_no_seq = 0

            for idx, root in enumerate(input_roots):
                root = str(root or "").strip().strip('"')
                exists = os.path.isdir(root) if root else False
                items = _scan_input_root_images(root) if exists else []
                no_seq_count = 0

                # 统计无序号文件数（只遍历一次）
                if exists and root:
                    try:
                        for dirpath, _, filenames in os.walk(root):
                            for name in filenames:
                                ext = os.path.splitext(name)[1].lower()
                                if ext not in _AUTOMATION_IMAGE_EXTS:
                                    continue
                                total_scanned += 1
                                stem = os.path.splitext(name)[0]
                                seq = _auto_extract_sequence(stem)
                                if not seq:
                                    no_seq_count += 1
                                    total_no_seq += 1
                    except Exception:
                        pass

                total_images += len(items)
                scan_reports.append({
                    "root_index": idx,
                    "root_path": root,
                    "exists": exists,
                    "scanned_file_count": total_scanned,
                    "image_count": len(items),
                    "sequence_count": len({it["sequence"] for it in items}),
                    "skipped_no_sequence_count": no_seq_count,
                    "error": "" if exists else "目录不存在",
                })

            # ── 构建分组 ───────────────────────────────────────────────────
            groups = _build_automation_sequence_groups(
                input_roots,
                output_root=output_root,
                require_all_roots_present=require_all,
            )

            scan_summary = {
                "root_count": len(input_roots),
                "scanned_file_count": total_scanned,
                "image_count": total_images,
                "group_count": len(groups),
                "skipped_no_sequence_count": total_no_seq,
            }

            # ── 为每组生成缩略图预览 ───────────────────────────────────────
            preview_groups: List[Dict[str, Any]] = []
            for g in groups:
                seq = str(g.get("sequence") or "")
                items = g.get("items") or []
                image_paths = _collect_automation_group_images(items, min(max_images_per_group, 4))

                preview_items: List[Dict[str, Any]] = []
                for img_path in image_paths:
                    item_meta = next(
                        (it for it in items if it.get("image_path") == img_path),
                        {},
                    )
                    thumb = ""
                    width = height = 0
                    try:
                        from PIL import ImageOps as _ImageOps
                        img = Image.open(img_path)
                        img = _ImageOps.exif_transpose(img).convert("RGB")
                        width, height = img.size
                        # 缩略图：长边 120px
                        long_edge = max(width, height)
                        if long_edge > 120:
                            scale = 120.0 / long_edge
                            img = img.resize(
                                (max(1, int(width * scale)), max(1, int(height * scale))),
                                Image.LANCZOS,
                            )
                        buf = BytesIO()
                        img.save(buf, format="PNG", compress_level=6)
                        thumb = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
                    except Exception as _te:
                        logger.warning(f"预览缩略图生成失败: {img_path} | {_te}")

                    preview_items.append({
                        "root_index": int(item_meta.get("root_index") or 0),
                        "root_path": str(item_meta.get("root_path") or ""),
                        "file_name": str(item_meta.get("file_name") or os.path.basename(img_path)),
                        "relative_path": str(item_meta.get("relative_path") or ""),
                        "image_path": img_path,
                        "sequence": seq,
                        "thumb_data_url": thumb,
                        "width": width,
                        "height": height,
                        "preview_error": "",
                    })

                preview_groups.append({
                    "sequence": seq,
                    "output_dir": str(g.get("output_dir") or ""),
                    "present_root_count": int(g.get("present_root_count") or len(items)),
                    "expected_root_count": int(g.get("expected_root_count") or len(input_roots)),
                    "preview_count": len(preview_items),
                    "preview_items": preview_items,
                    "items": [
                        {
                            "root_index": int(it.get("root_index") or 0),
                            "root_path": str(it.get("root_path") or ""),
                            "source_type": str(it.get("source_type") or "root_image"),
                            "file_name": str(it.get("file_name") or ""),
                            "image_path": str(it.get("image_path") or ""),
                            "sequence": seq,
                            "relative_path": str(it.get("relative_path") or ""),
                        }
                        for it in items
                    ],
                })

            return aiohttp_web.Response(
                content_type="application/json",
                text=json.dumps(
                    {
                        "ok": True,
                        "group_count": len(preview_groups),
                        "output_root": output_root,
                        "groups": preview_groups,
                        "scan_reports": scan_reports,
                        "scan_summary": scan_summary,
                    },
                    ensure_ascii=False,
                ),
            )

        except Exception as exc:
            logger.error(f"[/hrio-design/automation/preview] 处理失败: {exc}")
            return aiohttp_web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps(
                    {"ok": False, "error": str(exc), "groups": [], "scan_reports": [], "scan_summary": {}},
                    ensure_ascii=False,
                ),
            )
    # ── 注册所有路由 ──────────────────────────────────────────────────────────
    try:
        routes = [
            ("GET",  "/hrio-design/runtime",                       handle_runtime),
            ("POST", "/hrio-design/runtime/clear",                 handle_runtime_clear),
            ("GET",  "/hrio-design/config",                        handle_config),
            ("POST", "/hrio-design/automation/select-folder",      handle_automation_select_folder),
            ("POST", "/hrio-design/automation/preview",            handle_automation_preview),
        ]
        for method, path, handler in routes:
            try:
                server.app.router.add_route(method, path, handler)
                logger.info(f"[Hrio Design] 路由已注册: {method} {path}")
            except Exception as _re:
                # 路由已存在（热重载场景）忽略
                if "already" not in str(_re).lower():
                    logger.warning(f"[Hrio Design] 路由注册警告 {method} {path}: {_re}")
    except Exception as exc:
        logger.error(f"[Hrio Design] 路由批量注册失败: {exc}")
 
 
# 立即执行注册（模块加载时）
_register_hrio_routes()