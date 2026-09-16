# -*- coding: utf-8 -*-
"""Unit tests for task failure summarization (Ollama hint preservation)."""

from __future__ import annotations

import sys
import types
import unittest

_orig_data_provider_base = sys.modules.get("data_provider.base")
_orig_data_provider = sys.modules.get("data_provider")

if _orig_data_provider_base is None:
    base_mod = types.ModuleType("data_provider.base")
    base_mod.canonical_stock_code = lambda x: (x or "").strip().upper()
    base_mod.normalize_stock_code = lambda x: (x or "").strip().upper().removesuffix(".SH").removesuffix(".SZ")
    sys.modules["data_provider.base"] = base_mod

if _orig_data_provider is None:
    pkg_mod = types.ModuleType("data_provider")
    pkg_mod.base = sys.modules["data_provider.base"]
    sys.modules["data_provider"] = pkg_mod

from src.services.task_queue import summarize_task_failure

if _orig_data_provider_base is None:
    sys.modules.pop("data_provider.base", None)
else:
    sys.modules["data_provider.base"] = _orig_data_provider_base

if _orig_data_provider is None:
    sys.modules.pop("data_provider", None)
else:
    sys.modules["data_provider"] = _orig_data_provider


class SummarizeTaskFailureTest(unittest.TestCase):
    def test_ordinary_error_keeps_historical_truncation(self) -> None:
        error = "x" * 300
        task_error, message = summarize_task_failure(error)
        self.assertEqual(task_error, "x" * 200)
        self.assertEqual(message, "分析失败: " + "x" * 50)

    def test_ollama_hint_is_preserved_and_surfaced(self) -> None:
        error = (
            "All LLM models failed (tried 2 model(s)). Last error: APIConnectionError: "
            "litellm.APIConnectionError: OllamaException - [WinError 10061] No connection "
            "could be made because the target machine actively refused it. "
            "Ollama connection hint: the Ollama service looks unreachable for "
            "ollama/qwen3.5:9b, ollama/qwen3.8:27b. Start it with `ollama serve`, verify with "
            "`curl http://localhost:11434` (expect `Ollama is running`), then run "
            "`ollama list` and `ollama pull <model>` if the model is missing. See docs/FAQ.md Q12c."
        )
        task_error, message = summarize_task_failure(error)
        self.assertIn("Ollama connection hint:", task_error)
        self.assertIn("ollama serve", task_error)
        self.assertIn("ollama serve", message)
        self.assertIn("Q12c", message)

    def test_short_error_without_hint_is_unchanged(self) -> None:
        task_error, message = summarize_task_failure("分析返回空结果")
        self.assertEqual(task_error, "分析返回空结果")
        self.assertEqual(message, "分析失败: 分析返回空结果")


if __name__ == "__main__":
    unittest.main()
