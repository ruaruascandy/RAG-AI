from __future__ import annotations

import ast
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
        self.max_context_chunks = int(os.getenv("REVIEWER_MAX_CONTEXT_CHUNKS", "2"))
        self.max_context_chunk_chars = int(os.getenv("REVIEWER_MAX_CONTEXT_CHUNK_CHARS", "900"))
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
        cmd = ["ollama", "run", model_name, "--nowordwrap", "--hidethinking"]
        if self.response_format == "json":
            cmd.extend(["--format", "json"])
        result = subprocess.run(
            cmd,
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

    def _sanitize_output(self, text: str) -> str:
        # Remove ANSI escape sequences and carriage-return spinner artifacts from CLI output.
        text = re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)
        text = re.sub(r"\x1B[@-_][0-?]*[ -/]*[@-~]", "", text)
        text = text.replace("\r", "")
        text = "".join(ch for ch in text if ch in ("\n", "\t") or ord(ch) >= 32)
        return text.strip()

    def _index_to_line(self, text: str, index: int) -> int:
        if index < 0:
            return 1
        return text.count("\n", 0, index) + 1

    def _rule_based_issues(self, code: str) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        def add_issue(line: int, severity: str, message: str, suggestion: str) -> None:
            issues.append(
                {
                    "line": max(1, int(line)),
                    "severity": severity,
                    "message": message,
                    "suggestion": suggestion,
                }
            )

        for m in re.finditer(r"subprocess\.(?:check_output|run|Popen)\([^)]*shell\s*=\s*True", code):
            add_issue(
                self._index_to_line(code, m.start()),
                "高",
                "检测到 shell=True 的命令执行，存在命令注入风险。",
                "避免 shell=True，改为参数数组并对输入做白名单校验。",
            )

        for m in re.finditer(r"\b(?:eval|exec)\s*\(", code):
            add_issue(
                self._index_to_line(code, m.start()),
                "高",
                "检测到 eval/exec 动态执行，存在代码注入风险。",
                "避免直接执行用户输入，改为安全解析或受限解释器。",
            )

        for m in re.finditer(r"f[\"'][^\"']*\{[^\"']+\}[^\"']*[\"']", code):
            near = code[max(0, m.start() - 220) : min(len(code), m.end() + 220)]
            if re.search(r"\b(?:select|insert|update|delete|from|where)\b", near, flags=re.IGNORECASE):
                add_issue(
                    self._index_to_line(code, m.start()),
                    "高",
                    "检测到字符串拼接/插值 SQL，存在 SQL 注入风险。",
                    "使用参数化查询（占位符）而不是字符串拼接 SQL。",
                )

        for m in re.finditer(r"SECRET_KEY\s*=\s*[\"'][^\"']+[\"']", code):
            add_issue(
                self._index_to_line(code, m.start()),
                "中",
                "检测到硬编码密钥，存在泄漏风险。",
                "将密钥放到环境变量或密钥管理系统中。",
            )

        for m in re.finditer(r"hashlib\.md5\s*\(", code):
            add_issue(
                self._index_to_line(code, m.start()),
                "中",
                "检测到 MD5 哈希用于安全场景，不安全。",
                "改用 bcrypt/argon2/scrypt 等密码哈希算法。",
            )

        for m in re.finditer(r"os\.path\.join\([^)]*(?:file_name|filename|user_input|path)\s*\)", code):
            add_issue(
                self._index_to_line(code, m.start()),
                "中",
                "检测到可控路径拼接，存在路径遍历风险。",
                "规范化并校验路径，确保目标路径在允许目录内。",
            )

        for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s*=\s*open\s*\(", code, flags=re.MULTILINE):
            var_name = m.group(1)
            if re.search(rf"\b{re.escape(var_name)}\.close\s*\(", code) is None:
                add_issue(
                    self._index_to_line(code, m.start()),
                    "中",
                    "检测到文件打开后未显式关闭，可能导致资源泄漏。",
                    "优先使用 with open(...) as f 自动管理文件资源。",
                )

        # AST rules: stable baseline for common code quality defects.
        try:
            tree = ast.parse(code)
        except SyntaxError:
            tree = None

        if tree is not None:
            for node in tree.body:
                # top-level global variable naming
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            name = t.id
                            if re.search(r"[A-Z]", name) and re.search(r"[a-z]", name):
                                add_issue(
                                    getattr(t, "lineno", 1),
                                    "低",
                                    "检测到全局变量命名不规范（建议使用 UPPER_SNAKE_CASE）。",
                                    "将全局变量改为全大写下划线风格，例如 GLOBAL_VAR。",
                                )

                if not isinstance(node, ast.FunctionDef):
                    continue

                # unused parameters
                params = [a.arg for a in node.args.args]
                if params and params[0] in {"self", "cls"}:
                    params = params[1:]
                loaded = {
                    n.id
                    for n in ast.walk(node)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                }
                for p in params:
                    if p.startswith("_"):
                        continue
                    if p not in loaded:
                        add_issue(
                            getattr(node, "lineno", 1),
                            "低",
                            f"检测到未使用参数 `{p}`，可能增加维护成本。",
                            "删除未使用参数，或改为 `_` 前缀表示保留但未使用。",
                        )

                # open() without try/except in current function
                has_open_call = any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"
                    for n in ast.walk(node)
                )
                has_try_block = any(isinstance(n, ast.Try) for n in ast.walk(node))
                if has_open_call and not has_try_block:
                    add_issue(
                        getattr(node, "lineno", 1),
                        "中",
                        "检测到文件读取缺少异常处理，文件不存在时可能导致程序崩溃。",
                        "在文件 IO 处增加 try/except（至少处理 FileNotFoundError）。",
                    )

                # parameter attribute access without obvious None guard
                checked = set()
                for n in ast.walk(node):
                    if isinstance(n, ast.If):
                        test = n.test
                        if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name):
                            left = test.left.id
                            if test.comparators and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value is None:
                                checked.add(left)
                        elif isinstance(test, ast.Name):
                            checked.add(test.id)

                for n in ast.walk(node):
                    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                        base = n.value.id
                        if base in params and base not in checked:
                            add_issue(
                                getattr(n, "lineno", getattr(node, "lineno", 1)),
                                "中",
                                f"参数 `{base}` 直接进行属性访问（如 `.{n.attr}`），缺少空值校验。",
                                f"在使用 `{base}` 前增加 None/空值检查，避免运行时异常。",
                            )
                            break
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in issues:
            key = (item["line"], item["message"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _extract_json_values(self, text: str) -> List[Any]:
        decoder = json.JSONDecoder()
        values: List[Any] = []
        seen = set()

        # 1) Whole-text direct parse.
        direct = text.strip()
        if direct:
            try:
                value = json.loads(direct)
                marker = repr(value)[:300]
                if marker not in seen:
                    values.append(value)
                    seen.add(marker)
            except json.JSONDecodeError:
                pass

        # 2) Parse fenced blocks first (```json ... ```).
        fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        chunks = [*fenced_blocks, text]

        # 3) Scan each chunk for the first valid raw JSON object/array from any position.
        for chunk in chunks:
            candidate = chunk.strip()
            if not candidate:
                continue
            for i, ch in enumerate(candidate):
                if ch not in "{[":
                    continue
                try:
                    value, _ = decoder.raw_decode(candidate[i:])
                except json.JSONDecodeError:
                    continue
                marker = repr(value)[:300]
                if marker in seen:
                    continue
                values.append(value)
                seen.add(marker)
        return values

    def _parse_json_payload(self, output: str) -> Any | None:
        text = self._sanitize_output(output)
        if not text:
            return None

        for value in self._extract_json_values(text):
            if isinstance(value, (dict, list)):
                return value
        return None

    def review(
        self,
        code: str,
        context: List[str],
        query: str = "检查潜在的空指针异常、资源泄漏和逻辑错误",
    ) -> List[Dict[str, Any]]:
        safe_code = self._trim_text(code, self.max_code_chars)
        safe_context_chunks = [
            self._trim_text(chunk, self.max_context_chunk_chars)
            for chunk in context[: self.max_context_chunks]
        ]
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

要求:
1) 尽量全面，不要只返回最严重的一条；发现多个独立问题时请全部列出。
2) 优先覆盖：安全漏洞、异常处理、资源泄漏、逻辑错误、可维护性问题。
3) 不要编造不存在的问题；如果确实无问题，返回空数组。
4) 只输出合法 JSON，不要输出解释文字或 Markdown。

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
            return [
                {
                    "line": 1,
                    "severity": "中",
                    "message": "模型输出格式解析失败（非标准 JSON），该文件结果可能不完整。",
                    "suggestion": "可适当提高 REVIEWER_MAX_TOKENS（如 160/220），或切换 REVIEWER_TRANSPORT=http。",
                }
            ]

        if isinstance(data, dict):
            raw_issues = data.get("issues", [])
        elif isinstance(data, list):
            raw_issues = data
        else:
            raw_issues = []
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
        # Merge deterministic baseline checks to reduce model instability on small local models.
        merged = list(normalized)
        seen = {(item.get("line", 1), item.get("message", "")) for item in merged}
        for item in self._rule_based_issues(safe_code):
            key = (item.get("line", 1), item.get("message", ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

        # Soft dedupe by line+severity to reduce near-duplicate findings from model and rules.
        compact: List[Dict[str, Any]] = []
        compact_seen = set()
        for item in merged:
            key = (item.get("line", 1), item.get("severity", "中"))
            if key in compact_seen:
                continue
            compact_seen.add(key)
            compact.append(item)

        return compact


