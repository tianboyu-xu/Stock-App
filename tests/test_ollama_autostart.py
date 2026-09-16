# -*- coding: utf-8 -*-
"""Unit tests for Ollama auto-start on server startup (src.llm.ollama)."""

from __future__ import annotations

from types import SimpleNamespace

from src.llm.ollama import (
    ensure_ollama_running,
    is_loopback_host,
    parse_ollama_endpoint,
    resolve_configured_ollama_base_url,
    spawn_ollama_serve,
)


def test_explicit_ollama_model_uses_channel_base_url_first() -> None:
    env = {
        "LITELLM_MODEL": "ollama/qwen3.5:9b",
        "LLM_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_API_BASE": "http://127.0.0.1:9999",
    }
    assert resolve_configured_ollama_base_url(env) == "http://127.0.0.1:11434"


def test_explicit_ollama_model_falls_back_to_default() -> None:
    assert resolve_configured_ollama_base_url({"LITELLM_MODEL": "ollama/qwen3.5:9b"}) == (
        "http://127.0.0.1:11434"
    )


def test_enabled_ollama_channel_is_detected() -> None:
    env = {
        "LLM_CHANNELS": "ollama,opencode",
        "LLM_OLLAMA_PROTOCOL": "ollama",
        "LLM_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "LLM_OLLAMA_MODELS": "qwen3.5:9b,qwen3.8:27b",
        "LLM_OPENCODE_ENABLED": "false",
    }
    assert resolve_configured_ollama_base_url(env) == "http://127.0.0.1:11434"


def test_disabled_ollama_channel_is_ignored() -> None:
    env = {
        "LLM_CHANNELS": "ollama",
        "LLM_OLLAMA_ENABLED": "false",
        "LLM_OLLAMA_MODELS": "qwen3.5:9b",
    }
    assert resolve_configured_ollama_base_url(env) is None


def test_channel_without_models_is_ignored() -> None:
    env = {"LLM_CHANNELS": "ollama", "LLM_OLLAMA_PROTOCOL": "ollama"}
    assert resolve_configured_ollama_base_url(env) is None


def test_non_ollama_channel_is_ignored() -> None:
    env = {
        "LLM_CHANNELS": "deepseek",
        "LLM_DEEPSEEK_PROTOCOL": "deepseek",
        "LLM_DEEPSEEK_MODELS": "deepseek-chat",
    }
    assert resolve_configured_ollama_base_url(env) is None


def test_legacy_ollama_api_base_is_detected() -> None:
    env = {"OLLAMA_API_BASE": "http://127.0.0.1:11434", "OLLAMA_MODEL": "qwen3.5:9b"}
    assert resolve_configured_ollama_base_url(env) == "http://127.0.0.1:11434"


def test_empty_env_is_not_configured() -> None:
    assert resolve_configured_ollama_base_url({}) is None


def test_parse_default_endpoint_needs_no_serve_host() -> None:
    assert parse_ollama_endpoint("http://127.0.0.1:11434") == ("127.0.0.1", 11434, None)
    assert parse_ollama_endpoint("http://localhost:11434") == ("localhost", 11434, None)


def test_parse_custom_endpoint_sets_serve_host() -> None:
    assert parse_ollama_endpoint("http://127.0.0.1:11500") == (
        "127.0.0.1",
        11500,
        "127.0.0.1:11500",
    )


def test_parse_all_interfaces_normalizes_check_host() -> None:
    assert parse_ollama_endpoint("http://0.0.0.0:11434") == ("127.0.0.1", 11434, None)


def test_parse_invalid_endpoint_returns_none() -> None:
    assert parse_ollama_endpoint("") is None
    assert parse_ollama_endpoint("not-a-url") is None
    assert parse_ollama_endpoint("http://127.0.0.1:badport") is None


def test_loopback_detection() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("192.168.1.100")
    assert not is_loopback_host("host.docker.internal")


def test_ensure_skips_when_auto_start_disabled() -> None:
    calls: list = []
    env = {"LITELLM_MODEL": "ollama/qwen3.5:9b", "OLLAMA_AUTO_START": "false"}
    assert (
        ensure_ollama_running(
            env,
            _is_open=lambda host, port: calls.append((host, port)) or True,
            _spawn_serve=lambda serve_host: calls.append(("spawn", serve_host)) or True,
        )
        is False
    )
    assert calls == []


def test_ensure_skips_when_not_configured() -> None:
    calls: list = []
    assert (
        ensure_ollama_running(
            {},
            _is_open=lambda host, port: calls.append((host, port)) or True,
            _spawn_serve=lambda serve_host: calls.append(("spawn", serve_host)) or True,
        )
        is False
    )
    assert calls == []


def test_ensure_returns_true_without_spawning_when_already_running() -> None:
    calls: list = []
    env = {"LITELLM_MODEL": "ollama/qwen3.5:9b"}
    assert (
        ensure_ollama_running(
            env,
            _is_open=lambda host, port: calls.append((host, port)) or True,
            _spawn_serve=lambda serve_host: calls.append(("spawn", serve_host)) or True,
        )
        is True
    )
    assert calls == [("127.0.0.1", 11434)]


def test_ensure_starts_and_waits_for_readiness() -> None:
    states = {"open": False}
    calls: list = []

    def fake_is_open(host: str, port: int) -> bool:
        calls.append((host, port))
        return states["open"]

    def fake_spawn(serve_host: object) -> bool:
        calls.append(("spawn", serve_host))
        states["open"] = True
        return True

    env = {"LITELLM_MODEL": "ollama/qwen3.5:9b"}
    assert ensure_ollama_running(env, _is_open=fake_is_open, _spawn_serve=fake_spawn) is True
    assert ("spawn", None) in calls


def test_ensure_returns_false_when_spawn_fails() -> None:
    env = {"LITELLM_MODEL": "ollama/qwen3.5:9b"}
    assert (
        ensure_ollama_running(
            env,
            _is_open=lambda host, port: False,
            _spawn_serve=lambda serve_host: False,
        )
        is False
    )


def test_ensure_times_out_when_service_never_appears() -> None:
    env = {"LITELLM_MODEL": "ollama/qwen3.5:9b"}
    assert (
        ensure_ollama_running(
            env,
            timeout_seconds=0.01,
            _is_open=lambda host, port: False,
            _spawn_serve=lambda serve_host: True,
        )
        is False
    )


def test_ensure_never_starts_remote_hosts() -> None:
    calls: list = []
    env = {
        "LITELLM_MODEL": "ollama/qwen3.5:9b",
        "LLM_OLLAMA_BASE_URL": "http://192.168.1.100:11434",
    }
    assert (
        ensure_ollama_running(
            env,
            _is_open=lambda host, port: calls.append((host, port)) or False,
            _spawn_serve=lambda serve_host: calls.append(("spawn", serve_host)) or True,
        )
        is False
    )
    assert ("spawn", "192.168.1.100:11434") not in calls


def test_spawn_reports_missing_binary() -> None:
    assert spawn_ollama_serve(_which=lambda name: None) is False


def test_spawn_propagates_serve_host() -> None:
    seen: dict = {}

    def fake_popen(args: object, **kwargs: object) -> object:
        seen["args"] = args
        seen["env_host"] = kwargs["env"]["OLLAMA_HOST"]
        return SimpleNamespace(pid=1234)

    assert (
        spawn_ollama_serve(
            "127.0.0.1:11500",
            _which=lambda name: "/usr/bin/ollama",
            _popen=fake_popen,
        )
        is True
    )
    assert seen["args"] == ["/usr/bin/ollama", "serve"]
    assert seen["env_host"] == "127.0.0.1:11500"


def test_spawn_failure_returns_false() -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise OSError("nope")

    assert (
        spawn_ollama_serve(_which=lambda name: "/usr/bin/ollama", _popen=boom) is False
    )
