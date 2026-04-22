# vuln_project

This is an intentionally vulnerable mini project for testing code review and RAG audit flows.

## Run

```bash
python app.py
```

Then open:

- `http://127.0.0.1:8081/login?user=admin&pwd=admin123`
- `http://127.0.0.1:8081/run?cmd=dir`
- `http://127.0.0.1:8081/preview?file=index.html`
- `http://127.0.0.1:8081/calc?expr=1%2B2`

## Notes

The code contains deliberate security and logic flaws and should never be used in production.
