from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from threading import Lock
from typing import Any, Dict, List

import httpx


logger = logging.getLogger("code_review_backend.reviewer")


class Reviewer:
    def __init__(self, model: str | None = None):
        primary_model = model or os.getenv("REVIEWER_MODEL", "qwen2.5-coder:3b")
        fallback_models_raw = os.getenv(
            "REVIEWER_FALLBACK_MODELS",
            "deepseek-coder:6.7b-instruct-q4_0",
        )
        fallback_models = [m.strip() for m in fallback_models_raw.split(",") if m.strip()]
        self.models = [primary_model, *fallback_models]
        self.models = list(dict.fromkeys(self.models))
        self.model = self.models[0]
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.num_ctx = int(os.getenv("REVIEWER_NUM_CTX", "1024"))
        self.max_code_chars = int(os.getenv("REVIEWER_MAX_CODE_CHARS", "8000"))
        self.max_context_chars = int(os.getenv("REVIEWER_MAX_CONTEXT_CHARS", "12000"))
        self.max_response_tokens = int(os.getenv("REVIEWER_MAX_TOKENS", "160"))
        self.timeout_seconds = float(os.getenv("REVIEWER_TIMEOUT_SECONDS", "45"))
        self.max_retries = int(os.getenv("REVIEWER_MAX_RETRIES", "2"))
        self.retry_backoff_seconds = float(os.getenv("REVIEWER_RETRY_BACKOFF_SECONDS", "0.8"))
        self.transport = os.getenv("REVIEWER_TRANSPORT", "auto").strip().lower()
        self.response_format = os.getenv("REVIEWER_RESPONSE_FORMAT", "json").strip().lower()
        self._lock = Lock()

    def _trim_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n\n[内容过长，已截断]"

    def _short_exc(self, exc: Exception, limit: int = 240) -> str:
        text = f"{type(exc).__name__}: {exc}"
        return text if len(text) <= limit else (text[:limit] + "...")

    def _generate_once(self, model_name: str, prompt: str) -> str:
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "20m",
            "options": {
                "temperature": 0.1,
                "num_ctx": self.num_ctx,
                "num_predict": self.max_response_tokens,
            },
        }
        if self.response_format == "json":
            payload["format"] = "json"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.ollama_host}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()

    def _generate_via_cli(self, model_name: str, prompt: str) -> str:
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "http://127.0.0.1:11434"
        result = subprocess.run(
            ["ollama", "run", model_name],
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

    def _extract_json_candidates(self, text: str) -> List[str]:
        candidates: List[str] = []
        stack = 0
        start = -1
        for idx, ch in enumerate(text):
            if ch == "{":
                if stack == 0:
                    start = idx
                stack += 1
            elif ch == "}":
                if stack > 0:
                    stack -= 1
                    if stack == 0 and start >= 0:
                        candidates.append(text[start : idx + 1])
                        start = -1
        return candidates

    def _parse_json_payload(self, output: str) -> Dict[str, Any] | None:
        text = output.strip()
        if not text:
            return None

        # Some models wrap JSON inside markdown fences.
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        candidates: List[str] = [text]
        if fence_match:
            candidates.insert(0, fence_match.group(1).strip())

        candidates.extend(self._extract_json_candidates(text))
        seen = set()
        deduped_candidates = []
        for candidate in candidates:
            if candidate and candidate not in seen:
                deduped_candidates.append(candidate)
                seen.add(candidate)

        for candidate in deduped_candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
        return None

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

        start = time.perf_counter()
        output = ""
        used_transport = "none"
        used_model = ""
        errors: List[str] = []

        allow_http = self.transport in ("auto", "http")
        allow_cli = self.transport in ("auto", "cli")
        models_to_try = self.models

        for model_name in models_to_try:
            if allow_http:
                for attempt in range(1, self.max_retries + 2):
                    try:
                        with self._lock:
                            output = self._generate_once(model_name, prompt)
                        used_transport = "http"
                        used_model = model_name
                        logger.info(
                            "review_ok transport=%s model=%s attempt=%s duration_s=%.3f",
                            used_transport,
                            used_model,
                            attempt,
                            time.perf_counter() - start,
                        )
                        break
                    except Exception as exc:
                        short_exc = self._short_exc(exc)
                        errors.append(f"http[{model_name}#{attempt}] {short_exc}")
                        logger.warning(
                            "review_attempt_failed transport=http model=%s attempt=%s error=%s",
                            model_name,
                            attempt,
                            short_exc,
                        )
                        time.sleep(self.retry_backoff_seconds * attempt)

            if output:
                break

            if allow_cli:
                try:
                    with self._lock:
                        output = self._generate_via_cli(model_name, prompt)
                    used_transport = "cli"
                    used_model = model_name
                    logger.info(
                        "review_ok transport=%s model=%s duration_s=%.3f",
                        used_transport,
                        used_model,
                        time.perf_counter() - start,
                    )
                    break
                except Exception as exc:
                    short_exc = self._short_exc(exc)
                    errors.append(f"cli[{model_name}] {short_exc}")
                    logger.warning(
                        "review_attempt_failed transport=cli model=%s error=%s",
                        model_name,
                        short_exc,
                    )

        if not output:
            msg = "; ".join(errors[:3]) if errors else "unknown error"
            logger.error("review_failed duration_s=%.3f details=%s", time.perf_counter() - start, msg)
            return [
                {
                    "line": 1,
                    "severity": "高",
                    "message": f"Ollama 调用失败(已重试): {msg}",
                    "suggestion": "请确认 Ollama 在运行，模型可用；必要时切换小模型并降低并发请求。",
                }
            ]

        data = self._parse_json_payload(output)
        if data is None:
            output_preview = output[:180].replace("\n", "\\n")
            logger.warning(
                "review_parse_json_error transport=%s model=%s duration_s=%.3f",
                used_transport,
                used_model,
                time.perf_counter() - start,
            )
            logger.warning("review_parse_output_preview=%s", output_preview)
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

        logger.info(
            "review_done transport=%s model=%s issues=%s duration_s=%.3f",
            used_transport,
            used_model,
            len(normalized),
            time.perf_counter() - start,
        )
        return normalized
