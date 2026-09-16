# -*- coding: utf-8 -*-
"""Ollama service availability helper.

When the server starts, :func:`ensure_ollama_running` checks whether a
configured local Ollama service is reachable and starts it in the background
(``ollama serve``) when it is not. It never raises: every failure degrades to
a warning log so server startup is never blocked by Ollama.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from typing import Callable, Mapping, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_AUTO_START_ENV = "OLLAMA_AUTO_START"
OLLAMA_AUTO_START_TIMEOUT_ENV = "OLLAMA_AUTO_START_TIMEOUT_SECONDS"
OLLAMA_DEFAULT_START_TIMEOUT_SECONDS = 60.0
OLLAMA_START_POLL_INTERVAL_SECONDS = 0.5

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "0.0.0.0", "::1", "::"})
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSY_VALUES = frozenset({"0", "false", "no", "off"})


def _is_truthy(raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    cleaned = raw.strip().lower()
    if cleaned in _TRUTHY_VALUES:
        return True
    if cleaned in _FALSY_VALUES:
        return False
    return default


def _split_csv(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _non_empty(value: Optional[str]) -> str:
    return (value or "").strip()


def resolve_configured_ollama_base_url(
    env: Mapping[str, str] = os.environ,
) -> Optional[str]:
    """Return the configured Ollama base URL, or None when Ollama is unused.

    Mirrors the runtime model resolution order: an explicit ``ollama/`` primary
    model first, then the first enabled channel that resolves to the Ollama
    protocol, then the legacy ``OLLAMA_API_BASE`` variable.
    """

    explicit_model = _non_empty(env.get("LITELLM_MODEL", ""))
    if explicit_model.lower().startswith("ollama/"):
        return (
            _non_empty(env.get("LLM_OLLAMA_BASE_URL", ""))
            or _non_empty(env.get("OLLAMA_API_BASE", ""))
            or OLLAMA_DEFAULT_BASE_URL
        )

    for name in _split_csv(env.get("LLM_CHANNELS", "")):
        key = name.upper()
        if not _is_truthy(env.get(f"LLM_{key}_ENABLED", ""), True):
            continue
        models = _split_csv(env.get(f"LLM_{key}_MODELS", ""))
        if not models:
            continue
        protocol = _non_empty(env.get(f"LLM_{key}_PROTOCOL", "")).lower()
        if (
            protocol != "ollama"
            and name.strip().lower() != "ollama"
            and not any(model.lower().startswith("ollama/") for model in models)
        ):
            continue
        return (
            _non_empty(env.get(f"LLM_{key}_BASE_URL", ""))
            or _non_empty(env.get("OLLAMA_API_BASE", ""))
            or OLLAMA_DEFAULT_BASE_URL
        )

    legacy_base_url = _non_empty(env.get("OLLAMA_API_BASE", ""))
    if legacy_base_url:
        return legacy_base_url
    return None


def parse_ollama_endpoint(base_url: str) -> Optional[Tuple[str, int, Optional[str]]]:
    """Split a base URL into (check_host, port, serve_host_override).

    ``check_host`` is connectable (``0.0.0.0``/``::`` normalize to
    ``127.0.0.1``). ``serve_host_override`` is the ``OLLAMA_HOST`` value the
    child ``ollama serve`` needs, or None when Ollama defaults already match.
    """
    try:
        parsed = urlparse((base_url or "").strip())
    except ValueError:
        return None
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        return None
    scheme = (parsed.scheme or "http").lower()
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    check_host = "127.0.0.1" if hostname in ("0.0.0.0", "::") else hostname
    if (check_host, port) in (("127.0.0.1", 11434), ("localhost", 11434)):
        serve_host: Optional[str] = None
    else:
        serve_host = f"{hostname}:{port}"
    return check_host, port, serve_host


def is_loopback_host(hostname: str) -> bool:
    """Return True for addresses that refer to this machine."""
    return (hostname or "").strip().lower() in _LOOPBACK_HOSTS


def is_ollama_reachable(
    host: str,
    port: int,
    timeout_seconds: float = 2.0,
    _connect: Callable[..., object] = socket.create_connection,
) -> bool:
    """Return True when a TCP connection to the Ollama endpoint succeeds."""
    try:
        sock = _connect((host, port), timeout=timeout_seconds)
    except OSError:
        return False
    try:
        close = getattr(sock, "close", None)
        if callable(close):
            close()
    except OSError:
        pass
    return True


def spawn_ollama_serve(
    serve_host: Optional[str] = None,
    _which: Callable[[str], Optional[str]] = shutil.which,
    _popen: Callable[..., object] = subprocess.Popen,
) -> bool:
    """Start ``ollama serve`` detached in the background. Never raises."""
    executable = _which("ollama")
    if not executable:
        logger.warning(
            "Ollama 已配置但未启动，且本机找不到 ollama 可执行文件；"
            "请先安装 https://ollama.com ，或手动运行 `ollama serve`"
        )
        return False
    child_env = dict(os.environ)
    if serve_host:
        child_env["OLLAMA_HOST"] = serve_host
    try:
        if sys.platform == "win32":
            creationflags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
            proc = _popen(
                [executable, "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=False,
                creationflags=creationflags,
                env=child_env,
            )
        else:
            proc = _popen(
                [executable, "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                env=child_env,
            )
    except OSError as exc:
        logger.warning("后台启动 `ollama serve` 失败：%s", exc)
        return False
    pid = getattr(proc, "pid", "?")
    logger.info("已在后台启动 `ollama serve`（pid=%s），等待服务就绪…", pid)
    return True


def _resolve_start_timeout_seconds(env: Mapping[str, str] = os.environ) -> float:
    try:
        timeout = float(_non_empty(env.get(OLLAMA_AUTO_START_TIMEOUT_ENV, "")))
    except ValueError:
        return OLLAMA_DEFAULT_START_TIMEOUT_SECONDS
    if timeout != timeout or timeout <= 0:  # NaN or non-positive
        return OLLAMA_DEFAULT_START_TIMEOUT_SECONDS
    return timeout


def ensure_ollama_running(
    env: Mapping[str, str] = os.environ,
    timeout_seconds: Optional[float] = None,
    _is_open: Optional[Callable[[str, int], bool]] = None,
    _spawn_serve: Optional[Callable[[Optional[str]], bool]] = None,
) -> bool:
    """Ensure a configured local Ollama service is reachable. Never raises.

    Returns True when Ollama is reachable at the end of the call, False
    otherwise (not configured, auto-start disabled, remote host, binary
    missing, or start timeout). Server startup must never depend on the
    result.
    """
    if not _is_truthy(env.get(OLLAMA_AUTO_START_ENV, ""), True):
        logger.debug("Ollama 自启动已通过 %s 关闭", OLLAMA_AUTO_START_ENV)
        return False
    base_url = resolve_configured_ollama_base_url(env)
    if not base_url:
        logger.debug("未检测到 Ollama 配置，跳过 Ollama 自启动检查")
        return False
    endpoint = parse_ollama_endpoint(base_url)
    if endpoint is None:
        logger.warning("Ollama 地址 `%s` 无效，跳过自启动检查", base_url)
        return False
    check_host, port, serve_host = endpoint
    is_open = _is_open or is_ollama_reachable
    if is_open(check_host, port):
        logger.info("Ollama 服务已在运行（%s:%s）", check_host, port)
        return True
    if not is_loopback_host(check_host):
        logger.info(
            "Ollama 地址为远程主机（%s），无法在本机自动启动；"
            "请确认远端 `ollama serve` 正在运行并放行端口",
            base_url,
        )
        return False
    spawn = _spawn_serve or spawn_ollama_serve
    if not spawn(serve_host):
        return False
    if timeout_seconds is None:
        timeout_seconds = _resolve_start_timeout_seconds(env)
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    while time.monotonic() < deadline:
        if is_open(check_host, port):
            logger.info("Ollama 服务已就绪（%s:%s）", check_host, port)
            return True
        time.sleep(OLLAMA_START_POLL_INTERVAL_SECONDS)
    logger.warning(
        "等待 Ollama 服务就绪超时（%s:%s）；可手动运行 `ollama serve` 后重试，详见 docs/FAQ.md Q12c",
        check_host,
        port,
    )
    return False


