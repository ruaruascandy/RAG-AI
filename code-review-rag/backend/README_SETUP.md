# Backend setup

## GPU environment (AMD 7900 XTX / DirectML, Python 3.12)

```powershell
cd D:\RAG-AI\code-review-rag\backend
.\.venv312\Scripts\Activate.ps1
$env:RAG_EMBED_DEVICE="directml"
$env:HF_HUB_DISABLE_SYMLINKS="1"
$env:RAG_HF_HOME="D:\RAG-AI\hf_cache312"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Reviewer P0 defaults (recommended)

```powershell
$env:REVIEWER_MODEL="qwen2.5-coder:3b"
$env:REVIEWER_FALLBACK_MODELS="deepseek-coder:6.7b-instruct-q4_0"
$env:REVIEWER_NUM_CTX="1024"
$env:REVIEWER_MAX_TOKENS="160"
$env:REVIEWER_TIMEOUT_SECONDS="45"
$env:REVIEWER_MAX_RETRIES="2"
```

## Quick health check

```powershell
python -c "from fastapi.testclient import TestClient; import main; c=TestClient(main.app); print(c.get('/health').status_code, c.get('/health').json())"
```

## Notes

- `.venv312` is the DirectML-ready environment.
- If model download fails, the app will fall back to a hashing embedder so the API still runs.
- To reinstall dependencies in `.venv312`:

```powershell
python -m pip install -r requirements.txt
```
