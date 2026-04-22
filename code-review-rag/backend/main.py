from __future__ import annotations

import logging
import os
import time
from threading import Lock
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag import CodeRAG
from reviewer import Reviewer

app = FastAPI(title="Code Review RAG API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_rag: Optional[CodeRAG] = None
_reviewer: Optional[Reviewer] = None
_init_lock = Lock()
logger = logging.getLogger("code_review_backend")
DEFAULT_CODE_EXTENSIONS = [
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".kt",
    ".swift",
]
IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "__pycache__",
    ".venv",
    ".venv312",
    "venv",
    "hf_cache",
    "hf_cache312",
    "chroma_db",
}


def normalize_extensions(extensions: Optional[List[str]]) -> List[str]:
    configured = extensions
    if configured is None:
        env_value = os.getenv("PROJECT_CODE_EXTENSIONS", "").strip()
        if env_value:
            configured = [item.strip() for item in env_value.split(",")]
        else:
            configured = DEFAULT_CODE_EXTENSIONS

    normalized: List[str] = []
    for item in configured:
        ext = str(item).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        if ext not in normalized:
            normalized.append(ext)

    return normalized or DEFAULT_CODE_EXTENSIONS


def collect_code_files(folder_path: str, extensions: List[str]) -> List[str]:
    ext_set = {ext.lower() for ext in extensions}
    matched_files: List[str] = []

    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIR_NAMES and not d.startswith(".")]
        for name in files:
            _, ext = os.path.splitext(name)
            if ext.lower() in ext_set:
                matched_files.append(os.path.join(root, name))

    matched_files.sort()
    return matched_files


def get_rag() -> CodeRAG:
    global _rag
    if _rag is None:
        with _init_lock:
            if _rag is None:
                _rag = CodeRAG()
    return _rag


def get_reviewer() -> Reviewer:
    global _reviewer
    if _reviewer is None:
        with _init_lock:
            if _reviewer is None:
                _reviewer = Reviewer()
    return _reviewer


class ReviewRequest(BaseModel):
    code: str
    filename: Optional[str] = "code.py"
    query: Optional[str] = "检查潜在的空指针、资源泄漏和逻辑错误"


class Issue(BaseModel):
    file: Optional[str] = None
    line: int
    severity: str
    message: str
    suggestion: str


class ReviewResponse(BaseModel):
    issues: List[Issue]


class IndexRequest(BaseModel):
    folder_path: str
    extensions: Optional[List[str]] = None


class ContextReviewRequest(BaseModel):
    code: str
    current_file: str
    project_path: str
    query: Optional[str] = "检查潜在缺陷"


class ProjectFilesRequest(BaseModel):
    folder_path: str
    extensions: Optional[List[str]] = None


class ProjectReviewRequest(BaseModel):
    folder_path: str
    query: Optional[str] = "检查潜在缺陷"
    extensions: Optional[List[str]] = None
    max_files: int = 20
    max_file_chars: int = 5000


class ProjectReviewResponse(BaseModel):
    issues: List[Issue]
    reviewed_files: int
    total_files: int
    skipped_files: int
    duration_seconds: float


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/review", response_model=ReviewResponse)
async def review_code(req: ReviewRequest):
    rag = get_rag()
    reviewer = get_reviewer()
    issues: List[Issue] = []

    try:
        rag.add_code(req.code, req.filename or "code.py")
    except Exception:
        logger.exception("Failed to add code chunk for %s", req.filename)

    context: List[str] = []
    try:
        context = rag.search(req.query or "", top_k=3)
    except Exception:
        logger.exception("Failed to search context for /review")

    try:
        issues = reviewer.review(req.code, context, req.query or "")
    except Exception:
        logger.exception("Reviewer failed for /review")
        issues = [
            {
                "line": 1,
                "severity": "高",
                "message": "审查模型调用失败，请检查 Ollama 服务状态。",
                "suggestion": "确认 Ollama 已运行，并已拉取 deepseek-coder:6.7b-instruct-q4_0。",
            }
        ]
    return ReviewResponse(issues=issues)


@app.post("/index_project")
async def index_project(req: IndexRequest):
    if not os.path.exists(req.folder_path):
        raise HTTPException(status_code=404, detail="Folder not found")

    extensions = normalize_extensions(req.extensions)
    code_files = collect_code_files(req.folder_path, extensions)
    if not code_files:
        raise HTTPException(status_code=400, detail="No code files found")

    rag = get_rag()
    for file_path in code_files:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                code = handle.read()
            rel_path = os.path.relpath(file_path, req.folder_path)
            rag.add_code(code, rel_path)
        except Exception:
            logger.exception("Failed to index file: %s", file_path)

    return {"status": "ok", "indexed_files": len(code_files)}


@app.post("/review_with_context", response_model=ReviewResponse)
async def review_with_context(req: ContextReviewRequest):
    rag = get_rag()
    reviewer = get_reviewer()

    context_chunks: List[str] = []
    try:
        context_chunks = rag.search(req.code, top_k=5)
    except Exception:
        logger.exception("Failed to search context for /review_with_context")

    try:
        issues = reviewer.review(req.code, context_chunks, req.query or "检查潜在缺陷")
    except Exception:
        logger.exception("Reviewer failed for /review_with_context")
        issues = [
            {
                "line": 1,
                "severity": "高",
                "message": "审查模型调用失败，请检查 Ollama 服务状态。",
                "suggestion": "确认 Ollama 已运行，并已拉取 deepseek-coder:6.7b-instruct-q4_0。",
            }
        ]
    return ReviewResponse(issues=issues)


@app.post("/get_project_files")
async def get_project_files(req: ProjectFilesRequest):
    extensions = normalize_extensions(req.extensions)
    code_files = collect_code_files(req.folder_path, extensions)
    rel_paths = [os.path.relpath(path, req.folder_path) for path in code_files]
    return {"files": rel_paths}


@app.post("/review_project", response_model=ProjectReviewResponse)
async def review_project(req: ProjectReviewRequest):
    if not os.path.exists(req.folder_path):
        raise HTTPException(status_code=404, detail="Folder not found")

    extensions = normalize_extensions(req.extensions)
    code_files = collect_code_files(req.folder_path, extensions)
    if not code_files:
        raise HTTPException(status_code=400, detail="No code files found")

    max_files = max(1, min(req.max_files, 200))
    max_file_chars = max(200, min(req.max_file_chars, 30000))
    target_files = code_files[:max_files]

    rag = get_rag()
    reviewer = get_reviewer()
    issues: List[Issue] = []
    skipped_files = 0
    reviewed_files = 0
    start = time.perf_counter()
    max_issues = int(os.getenv("PROJECT_REVIEW_MAX_ISSUES", "400"))

    for abs_path in target_files:
        reviewed_files += 1
        rel_path = os.path.relpath(abs_path, req.folder_path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as handle:
                code = handle.read()
        except Exception:
            logger.exception("Failed to read file for /review_project: %s", abs_path)
            skipped_files += 1
            issues.append(
                {
                    "file": rel_path,
                    "line": 1,
                    "severity": "高",
                    "message": "文件读取失败，未能完成审查。",
                    "suggestion": "请检查文件编码或访问权限后重试。",
                }
            )
            continue

        if not code.strip():
            skipped_files += 1
            continue

        code_for_review = code[:max_file_chars]

        try:
            rag.add_code(code_for_review, rel_path)
        except Exception:
            logger.exception("Failed to add code chunk in /review_project: %s", rel_path)

        context_chunks: List[str] = []
        try:
            context_chunks = rag.search(code_for_review, top_k=5)
        except Exception:
            logger.exception("Failed to search context in /review_project: %s", rel_path)

        try:
            current_issues = reviewer.review(
                code_for_review,
                context_chunks,
                req.query or "检查潜在缺陷",
            )
        except Exception:
            logger.exception("Reviewer failed in /review_project: %s", rel_path)
            current_issues = [
                {
                    "line": 1,
                    "severity": "高",
                    "message": "审查模型调用失败，请检查 Ollama 服务状态。",
                    "suggestion": "确认 Ollama 已运行，必要时降低并发并切换小模型。",
                }
            ]

        for item in current_issues:
            enriched = {
                "file": rel_path,
                "line": item.get("line", 1),
                "severity": item.get("severity", "中"),
                "message": item.get("message", "未提供问题描述"),
                "suggestion": item.get("suggestion", "请人工复核该位置逻辑"),
            }
            issues.append(enriched)

        if len(issues) >= max_issues:
            logger.info("review_project reached max issues limit=%s", max_issues)
            break

    return ProjectReviewResponse(
        issues=issues,
        reviewed_files=reviewed_files,
        total_files=len(code_files),
        skipped_files=skipped_files,
        duration_seconds=round(time.perf_counter() - start, 3),
    )


@app.get("/read_file")
async def read_file(path: str = Query(...)):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        return {"content": content}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
