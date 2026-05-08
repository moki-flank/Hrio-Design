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
_AUTOMATION_HISTORY_LOCK = threading.Lock()
_AUTOMATION_HISTORY_MAX_ITEMS = 500

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


def _tensor_to_preview_data_url(tensor: torch.Tensor, max_edge: int = 900) -> str:
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


def _save_tensors_for_comfyui_preview(tensors: List[Any], label: str = "banana") -> List[Dict[str, str]]:
    """
    保存临时预览图，返回 ComfyUI 前端能识别的 ui.images 结构。
    这样节点本身面板能直接显示图片，同时 result 仍保留 IMAGE 张量给 Preview Image 节点继续预览。
    """
    results: List[Dict[str, str]] = []
    try:
        import folder_paths  # type: ignore
        output_dir = folder_paths.get_temp_directory()
        subfolder = ""
        image_type = "temp"
    except Exception:
        output_dir = os.path.join(MODULE_DIR, "banana_temp_previews")
        subfolder = ""
        image_type = "temp"

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
                results.append({"filename": filename, "subfolder": subfolder, "type": image_type})
            except Exception as e:
                logger.warning(f"ComfyUI 临时预览图保存失败，已跳过一帧: {e}")

    return results


def _return_images_with_ui_preview(result_tuple: Tuple[Any, ...], label: str = "banana") -> Dict[str, Any] | Tuple[Any, ...]:
    try:
        preview_tensors = [x for x in list(result_tuple[:3]) if x is not None]
        ui_images = _save_tensors_for_comfyui_preview(preview_tensors, label=label)
        if ui_images:
            return {"ui": {"images": ui_images}, "result": tuple(result_tuple)}
    except Exception as e:
        logger.warning(f"ComfyUI ui.images 预览输出失败，继续返回 IMAGE 张量: {e}")
    return tuple(result_tuple)



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
    }
    return [item], local_path



def _return_video_with_ui_preview(result_tuple: Tuple[Any, ...], video_url_or_path: Any, label: str = "banana_video") -> Dict[str, Any] | Tuple[Any, ...]:
    try:
        ui_videos, local_path = _save_video_for_comfyui_preview(video_url_or_path, label=label)
        if local_path:
            result_list = list(result_tuple)
            # 兼容两类输出：
            # 1. 老视频节点: (info, video, mp4url) -> video 输出本地可预览路径；
            # 2. 新普通单输出视频节点: (video,) -> 唯一输出直接给本地可预览路径。
            if len(result_list) == 1:
                result_list[0] = local_path
            elif len(result_list) >= 2:
                result_list[1] = local_path
            result_tuple = tuple(result_list)
        if ui_videos:
            return {"ui": {"videos": ui_videos}, "result": tuple(result_tuple)}
    except Exception as e:
        logger.warning(f"ComfyUI ui.videos 预览输出失败，继续返回原始结果: {e}")
    return tuple(result_tuple)


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
            "image": _tensor_to_preview_data_url(item.get("tensor")) if item.get("tensor") is not None else "",
        }
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
        "has_error": any(v.get("needs_regenerate") for v in views.values()),
        "views": views,
    }
    _LAST_THREE_VIEW_LATEST_KEY = key


def _runtime_results_payload() -> Dict[str, Any]:
    groups = sorted(
        _LAST_THREE_VIEW_RUNTIME.values(),
        key=lambda x: float(x.get("updated_at") or 0),
        reverse=True,
    )
    return {
        "ok": True,
        "latest_key": _LAST_THREE_VIEW_LATEST_KEY,
        "count": len(groups),
        "groups": groups,
    }


def _clear_runtime_results() -> Dict[str, Any]:
    global _LAST_THREE_VIEW_LATEST_KEY
    _LAST_THREE_VIEW_RUNTIME.clear()
    _LAST_THREE_VIEW_LATEST_KEY = ""
    return {"ok": True, "message": "已清空 Hrio Design 三方案运行期预览缓存"}

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
    parts = []

    if str(global_prompt or "").strip():
        parts.append(str(global_prompt).strip())

    if str(view_prompt or "").strip():
        parts.append(str(view_prompt).strip())

    if str(negative_prompt or "").strip():
        parts.append("负面约束：" + str(negative_prompt).strip())

    parts.append(
        "输出要求：单张完整图片，不要拼图，不要三联图，不要九宫格，不要文字标注，不要水印。"
        "主体边缘清晰，结构准确，光影干净，适合平面设计或室内设计提案使用。"
    )

    return "\n\n".join(parts)




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
    return bool(data) and _value_as_bool(data.get("enabled"), False)


def _auto_normalize_payload(raw: Any, *, save_images_default: bool = True, save_video_default: bool = False) -> Dict[str, Any]:
    data = _auto_payload_from_string(raw)
    input_roots = _auto_clean_path_list(data.get("input_roots") or data.get("inputFolders") or data.get("input_folders"), 10)
    output_root = str(data.get("output_root") or data.get("outputRoot") or "").strip()
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
    return {
        "enabled": _value_as_bool(data.get("enabled"), False),
        "version": str(data.get("version") or "7.9.0"),
        "input_roots": input_roots,
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
        },
    }


def _scan_input_root_images(root: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    root = str(root or "").strip()
    if not root or not os.path.isdir(root):
        return items
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return items
    for name in names:
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in _AUTOMATION_IMAGE_EXTS:
            continue
        seq = _auto_extract_sequence(os.path.splitext(name)[0])
        if not seq:
            continue
        items.append({
            "source_type": "root_image",
            "file_name": name,
            "image_path": full,
            "sequence": seq,
        })
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
        img = Image.open(path).convert("RGB")
        tensors.append(_pil_to_tensor(img))
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
    names = ["front.png", "side.png", "back.png", "result.mp4", "run_info.json", "error.txt"]
    out: Dict[str, str] = {}
    for name in names:
        path = os.path.join(output_dir, name) if output_dir else ""
        if path and os.path.exists(path):
            out[name] = path
    return out


def _read_automation_history_file() -> Dict[str, Any]:
    path = _automation_history_path()
    if not os.path.exists(path):
        return {"ok": True, "version": "7.10.0", "updated_at_ms": 0, "count": 0, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"ok": True, "version": "7.10.0", "updated_at_ms": 0, "count": 0, "items": []}
    if not isinstance(data, dict):
        data = {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return {
        "ok": True,
        "version": str(data.get("version") or "7.10.0"),
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
    item.setdefault("created_at_ms", _automation_history_now_ms())
    item.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    item.setdefault("plugin_version", "7.10.0")
    with _AUTOMATION_HISTORY_LOCK:
        data = _read_automation_history_file()
        items = data.get("items") if isinstance(data.get("items"), list) else []
        items.append(item)
        items = items[-_AUTOMATION_HISTORY_MAX_ITEMS:]
        payload = {
            "ok": True,
            "version": "7.10.0",
            "updated_at_ms": _automation_history_now_ms(),
            "count": len(items),
            "items": items,
        }
        with open(_automation_history_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


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
            "node_type": "video",
            "output_dir": run_dir,
            "error": str(e),
            "model": video_model,
            "video_resolution": _normalize_video_resolution(video_resolution),
            "aspect_ratio": _normalize_video_aspect_ratio(aspect_ratio),
        }
        _append_automation_history_record(fail_meta)
        return fail_meta

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
            "global_prompt": ("STRING", {"default": "通用设计要求：面向平面设计师与室内设计师，输出专业设计提案级画面。请保持参考图的核心设计语言、色彩气质、材质关系、空间比例或版式秩序；画面高级、干净、真实、可落地，不要生成真实文字。", "multiline": True, "tooltip": "会自动拼到方案 A/B/C 三个提示词前面，用于控制整体设计方向。"}),
            "negative_prompt": ("STRING", {"default": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格标签，不要促销元素，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要错误透视，不要杂乱拼贴，不要廉价滤镜。", "multiline": True, "tooltip": "会自动拼到三个方案提示词里。"}),
            "automation_payload": ("STRING", {"default": "", "multiline": True, "tooltip": "自动化批处理 JSON；启用后会扫描最多 10 个输入根目录下的同序号图片并发处理。"}),
        }

        slot_count = int(cfg.get("optional_image_slots") or _NODE.get("optional_image_slots", 10) or 10)
        for i in range(1, slot_count + 1):
            optional[f"image_{i}"] = ("IMAGE", {"tooltip": f"参考图 {i}；同一批上传图会复用到正面/侧面/背面三个并发请求"})

        return {"required": required, "optional": optional, "hidden": {"unique_id": "UNIQUE_ID"}}

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
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")

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
        if not cfg.get("input_roots"):
            msg = "自动化已启用，但没有 input_roots。请在自动化面板选择输入根目录。"
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")
        if not cfg.get("output_root"):
            msg = "自动化已启用，但没有 output_root。请在自动化面板选择输出根目录。"
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_error")
        groups = _build_automation_sequence_groups(
            cfg["input_roots"],
            output_root=cfg["output_root"],
            require_all_roots_present=bool(cfg.get("require_all_roots_present")),
        )
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
        group_concurrency = int(cfg.get("group_concurrency") or 3)
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
            f"input_roots: {len(cfg['input_roots'])}",
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
            "negative_prompt": (
                "STRING",
                {
                    "default": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格标签，不要促销元素，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要错误透视，不要畸形结构，不要廉价滤镜。",
                    "multiline": True,
                    "tooltip": "负面提示词，会拼进请求提示词里。",
                },
            ),
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
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    def generate(
        self,
        prompt: str,
        model: str,
        api_key: str = "",
        image_size: str = "2K",
        aspect_ratio: str = "Auto",
        negative_prompt: str = "",
        unique_id=None,
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")

        if not resolved_key:
            msg = "请在节点中填入 API Key，或在 config.ini 的 [banana] 下配置 api_key"
            logger.error(msg)
            return _return_images_with_ui_preview((_error_img(msg),), label="banana_normal_single_error")

        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            msg = "请填写单图提示词"
            logger.error(msg)
            return _return_images_with_ui_preview((_error_img(msg),), label="banana_normal_single_error")

        final_prompt = clean_prompt
        if str(negative_prompt or "").strip():
            final_prompt += "\n\n负面约束：" + str(negative_prompt).strip()
        final_prompt += "\n\n输出要求：只输出一张完整图片，不要拼图，不要多视图排版，不要文字标注，不要水印。"

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
            return _return_images_with_ui_preview((image_out,), label="banana_normal_single_image")
        except Exception as e:
            msg = str(e)[:2500]
            logger.error(f"普通单图节点生成失败: {msg}")
            return _return_images_with_ui_preview((_error_img(f"普通单图节点生成失败：{msg[:220]}"),), label="banana_normal_single_error")


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

        optional = {}
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
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    def generate(
        self,
        prompt: str,
        video_model: str,
        api_key: str = "",
        video_resolution: str = "1080p",
        aspect_ratio: str = "16:9 (横屏宽幅)",
        unique_id=None,
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")

        if not resolved_key:
            msg = "请在节点中填入 API Key，或在 config.ini 的 [banana] 下配置 api_key"
            logger.error(msg)
            return _return_video_with_ui_preview(("",), "", label="banana_normal_video_single_error")

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
            "automation_payload": (
                "STRING",
                {
                    "default": "",
                    "multiline": True,
                    "tooltip": "自动化批处理 JSON；由右下角自动化面板写入，界面会自动隐藏。",
                },
            ),
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
            "hidden": {"unique_id": "UNIQUE_ID"},
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
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")

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
        if not cfg.get("input_roots"):
            return _return_video_with_ui_preview(("❌ Hrio Design 生视频自动化失败\n自动化已启用，但没有 input_roots。", "", ""), "", label="banana_video_automation_error")
        if not cfg.get("output_root"):
            return _return_video_with_ui_preview(("❌ Hrio Design 生视频自动化失败\n自动化已启用，但没有 output_root。", "", ""), "", label="banana_video_automation_error")
        groups = _build_automation_sequence_groups(
            cfg["input_roots"],
            output_root=cfg["output_root"],
            require_all_roots_present=bool(cfg.get("require_all_roots_present")),
        )
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
            f"input_roots: {len(cfg['input_roots'])}",
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
]
