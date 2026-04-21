from fastapi import FastAPI, HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import tempfile
import os
from rag import CodeRAG
from reviewer import Reviewer
import glob


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化RAG和Reviewer（全局单例）
rag = CodeRAG()
reviewer = Reviewer()

class ReviewRequest(BaseModel):
    code: str
    filename: Optional[str] = "code.py"
    query: Optional[str] = "检查潜在的空指针异常、资源泄漏、逻辑错误"

class Issue(BaseModel):
    line: int
    severity: str
    message: str
    suggestion: str

class ReviewResponse(BaseModel):
    issues: List[Issue]

class ProjectReviewRequest(BaseModel):
    folder_path: str

class ContextReviewRequest(BaseModel):
    code: str
    current_file: str
    project_path: str

@app.post("/review", response_model=ReviewResponse)
async def review_code(req: ReviewRequest):
    # 将当前代码加入向量库（临时索引）
    rag.add_code(req.code, req.filename)
    # 检索相关上下文（用审查查询作为检索条件）
    context = rag.search(req.query, top_k=3)
    # 调用LLM生成审查意见
    issues = reviewer.review(req.code, context, req.query)
    return ReviewResponse(issues=issues)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


class IndexRequest(BaseModel):
    folder_path: str

@app.post("/index_project")
async def index_project(req: IndexRequest):
    if not os.path.exists(req.folder_path):
        raise HTTPException(status_code=404, detail="Folder not found")
    
    py_files = glob.glob(os.path.join(req.folder_path, "**/*.py"), recursive=True)
    if not py_files:
        raise HTTPException(status_code=400, detail="No Python files found")
    
    # 清空旧索引（可选）
    # rag.clear_collection()
    
    for file_path in py_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        # 使用相对路径作为标识
        rel_path = os.path.relpath(file_path, req.folder_path)
        rag.add_code(code, rel_path)
    
    return {"status": "ok", "indexed_files": len(py_files)}

class ContextReviewRequest(BaseModel):
    code: str
    current_file: str
    project_path: str

@app.post("/review_with_context")
async def review_with_context(req: ContextReviewRequest):
    # 1. 将当前代码作为查询，检索整个项目中相关的块
    context_chunks = rag.search(req.code, top_k=5)
    # 2. 调用 LLM 审查，传入当前代码和检索到的上下文
    issues = reviewer.review(req.code, context_chunks, "检查潜在缺陷")
    return ReviewResponse(issues=issues)

class ProjectFilesRequest(BaseModel):
    folder_path: str

@app.post("/get_project_files")
async def get_project_files(req: ProjectFilesRequest):
    # 递归查找所有 .py 文件
    pattern = os.path.join(req.folder_path, "**", "*.py")
    py_files = glob.glob(pattern, recursive=True)
    # 转换为相对路径
    rel_paths = [os.path.relpath(f, req.folder_path) for f in py_files]
    return {"files": rel_paths}

@app.get("/read_file")
async def read_file(path: str = Query(...)):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/review_project")
async def review_project(req: ProjectReviewRequest):
        # 先确保项目已索引（或自动索引）
        # 遍历所有块，对每个块进行审查（或合并后审查）
        # 返回每个文件的问题列表
    pass    