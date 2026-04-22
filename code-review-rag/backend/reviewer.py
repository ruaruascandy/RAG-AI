from __future__ import annotations

import json
import os
import re
import subprocess
import time
from threading import Lock
from typing import Any, Dict, List

import httpx


class Reviewer:
    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("REVIEWER_MODEL", "deepseek-coder:6.7b-instruct-q4_0")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.num_ctx = int(os.getenv("REVIEWER_NUM_CTX", "2048"))
        self.max_code_chars = int(os.getenv("REVIEWER_MAX_CODE_CHARS", "8000"))
        self.max_context_chars = int(os.getenv("REVIEWER_MAX_CONTEXT_CHARS", "12000"))
        self.max_response_tokens = int(os.getenv("REVIEWER_MAX_TOKENS", "256"))
        self.timeout_seconds = float(os.getenv("REVIEWER_TIMEOUT_SECONDS", "120"))
        self._lock = Lock()

    def _trim_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n\n[内容过长，已截断]"

    def _generate_once(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "20m",
            "options": {
                "temperature": 0.1,
                "num_ctx": self.num_ctx,
                "num_predict": self.max_response_tokens,
            },
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.ollama_host}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()

    def _generate_via_cli(self, prompt: str) -> str:
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "http://127.0.0.1:11434"
        result = subprocess.run(
            ["ollama", "run", self.model],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=self.timeout_seconds + 30,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="ignore").strip()
            if len(stderr) > 300:
                stderr = stderr[:300] + "..."
            raise RuntimeError(stderr or f"ollama run exited with code {result.returncode}")
        return (result.stdout or b"").decode("utf-8", errors="ignore").strip()

    def review(
        self,
        code: str,
        context: List[str],
        query: str = "检查潜在的空指针异常、资源泄漏和逻辑错误",
    ) -> List[Dict[str, Any]]:
        safe_code = self._trim_text(code, self.max_code_chars)
        safe_context_chunks = [self._trim_text(chunk, 2500) for chunk in context[:5]]
        context_text = "\n\n---\n\n".join(safe_context_chunks) if safe_context_chunks else "无相关上下文"
        context_text = self._trim_text(context_text, self.max_context_chars)

        prompt = f"""
你是一名资深 Python 代码审查专家。请基于相关上下文审查用户代码。

相关代码片段:
{context_text}

用户代码:
{safe_code}

审查重点:
{query}

请只输出 JSON，不要输出其他文本，格式如下:
{{
  "issues": [
    {{
      "line": 12,
      "severity": "高|中|低",
      "message": "问题描述",
      "suggestion": "修改建议"
    }}
  ]
}}
""".strip()

        last_error: Exception | None = None
        output = ""
        for _ in range(3):
            try:
                with self._lock:
                    output = self._generate_once(prompt)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                time.sleep(1.0)

        if last_error is not None:
            # API unstable on some Windows setups; fallback to CLI path.
            try:
                with self._lock:
                    output = self._generate_via_cli(prompt)
                last_error = None
            except Exception as cli_exc:
                return [
                    {
                        "line": 1,
                        "severity": "高",
                        "message": f"Ollama 调用失败(HTTP与CLI均失败): {last_error}; CLI: {cli_exc}",
                        "suggestion": "请确认 Ollama 在运行，模型可用；必要时重启 Ollama 并降低并发请求。",
                    }
                ]

        match = re.search(r"\{.*\}", output, re.DOTALL)
        if not match:
            return []

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return []

        raw_issues = data.get("issues", [])
        if not isinstance(raw_issues, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for issue in raw_issues:
            if not isinstance(issue, dict):
                continue

            line = issue.get("line", 1)
            try:
                line = int(line)
            except (ValueError, TypeError):
                line = 1

            severity = str(issue.get("severity", "中")).strip().lower()
            severity_map = {
                "high": "高",
                "medium": "中",
                "low": "低",
                "高": "高",
                "中": "中",
                "低": "低",
            }
            severity_cn = severity_map.get(severity, "中")

            normalized.append(
                {
                    "line": max(1, line),
                    "severity": severity_cn,
                    "message": str(issue.get("message", "未提供问题描述")),
                    "suggestion": str(issue.get("suggestion", "请人工复核该位置逻辑")),
                }
            )

        return normalized
