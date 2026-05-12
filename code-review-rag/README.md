# Code Review RAG (v2.2)

AI-assisted code review tool with:
- Single-file review
- Full-project review
- Project index + context retrieval (RAG)
- Multi-language extension filtering (Python/Java/C++/JS/TS and more)
- Electron desktop mode (optional)

## Repository Version

- Recommended branch: `v2.2`
- Recommended commit: `0d7f2ba`

If you want to reproduce exactly the same result as my demo, please use the branch/commit above.

## Tech Stack

- Backend: FastAPI, ChromaDB, Sentence-Transformers, Ollama
- Frontend: React + TypeScript + Monaco Editor
- Desktop: Electron
- OS tested: Windows (PowerShell)

## Project Structure

```text
code-review-rag/
  backend/                 # FastAPI + RAG + reviewer logic
  frontend/                # React UI + Monaco + Electron bridge
  test_file/               # Test projects/files
  start-dev.ps1            # One-click startup script (backend + frontend)
  start-dev.cmd
  start-ollama-gpu.ps1     # GPU selection helper for Ollama (AMD scenarios)
  start-ollama-gpu.cmd
```

## Prerequisites

1. Python 3.12 (recommended for current backend venv)
2. Node.js 18+ and npm
3. Ollama installed and running
4. Pull at least one review model in Ollama

Example:

```powershell
ollama pull qwen2.5-coder:3b
ollama pull deepseek-coder:6.7b-instruct-q4_0
```

## Backend Setup

```powershell
cd backend
python -m venv .venv312
.\.venv312\Scripts\Activate.ps1
pip install -U pip setuptools wheel
pip install -r requirements.txt
```

## Frontend Setup

```powershell
cd frontend
npm install
```

## One-Click Start (Recommended)

From repository root:

```powershell
cd D:\RAG-AI\code-review-rag
.\start-dev.ps1
```

This starts:
- Backend at `http://localhost:8000`
- Frontend at `http://localhost:3000`

Start with Electron window as well:

```powershell
.\start-dev.ps1 -WithElectron
```

## Manual Start (Alternative)

Backend:

```powershell
cd backend
.\.venv312\Scripts\Activate.ps1
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```powershell
cd frontend
npm run start
```

Electron (after frontend dev server is ready):

```powershell
cd frontend
npm run electron
```

## Main API Endpoints

- `GET /health`
- `POST /review` (single file)
- `POST /review_with_context` (single file + RAG context)
- `POST /index_project` (build project index)
- `POST /get_project_files` (enumerate reviewable files)
- `POST /review_project` (project-level review)
- `GET /read_file` (read selected source file)

## Multi-language Review Support

Current extension-based filtering supports:

- `.py`
- `.js`, `.jsx`, `.ts`, `.tsx`
- `.java`
- `.cpp`, `.cc`, `.cxx`, `.c`, `.h`, `.hpp`, `.hh`, `.hxx`
- `.go`, `.rs`, `.cs`, `.php`, `.rb`, `.kt`, `.swift`

Note:
- Review quality depends on model capability and prompt/JSON formatting stability.
- Some outputs may require retry or fallback model.

## Known Limitations

1. LLM output may occasionally be non-standard JSON; parser fallback will reduce hard failures but can still lose details.
2. Full-project review is bounded by file count/size parameters for stability.
3. On unstable network or model cold-start, Ollama calls may timeout.
4. AMD GPU acceleration depends on local Ollama + ROCm compatibility; CPU fallback can still work.

## Troubleshooting

1. `ERR_CONNECTION_REFUSED` in Electron:
- Start frontend first: `npm run start`
- Then run: `npm run electron`

2. Backend shows model call failures:
- Ensure Ollama is running: `ollama ps`
- Warm up model once: `ollama run qwen2.5-coder:3b "ok"`
- Increase timeout / reduce max tokens / reduce input chars

3. Review returns too few issues:
- Increase `REVIEWER_MAX_TOKENS`
- Use a stronger model or fallback chain
- Reduce per-file truncation (`REVIEWER_MAX_CODE_CHARS`) only when needed

## For Supervisor/Instructor Review

Recommended submission information:

1. Repository URL
2. Branch name: `v2.2`
3. Commit hash: `0d7f2ba`
4. This README for setup and reproduction

