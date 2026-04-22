from __future__ import annotations

import glob
import logging
import os
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
    line: int
    severity: str
    message: str
    suggestion: str


class ReviewResponse(BaseModel):
    issues: List[Issue]


class IndexRequest(BaseModel):
    folder_path: str


class ContextReviewRequest(BaseModel):
    code: str
    current_file: str
    project_path: str


class ProjectFilesRequest(BaseModel):
    folder_path: str


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

    py_files = glob.glob(os.path.join(req.folder_path, "**", "*.py"), recursive=True)
    if not py_files:
        raise HTTPException(status_code=400, detail="No Python files found")

    rag = get_rag()
    for file_path in py_files:
        with open(file_path, "r", encoding="utf-8") as handle:
            code = handle.read()
        rel_path = os.path.relpath(file_path, req.folder_path)
        rag.add_code(code, rel_path)

    return {"status": "ok", "indexed_files": len(py_files)}


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
        issues = reviewer.review(req.code, context_chunks, "检查潜在缺陷")
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
    pattern = os.path.join(req.folder_path, "**", "*.py")
    py_files = glob.glob(pattern, recursive=True)
    rel_paths = [os.path.relpath(path, req.folder_path) for path in py_files]
    return {"files": rel_paths}


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
