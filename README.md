# InterviewForgeAI Backend

This project is a minimal FastAPI backend initialized with `uv` for modern Python dependency and environment management.

## What has been done

- Initialized the project with `uv init --app --name interviewforgeai_backend .`
- Created a `pyproject.toml` project manifest
- Installed `fastapi` and `uvicorn[standard]` using `uv add`
- Created a minimal FastAPI app in `main.py`
- Configured dependency isolation using `uv` and an auto-created `.venv`

## Project files

- `pyproject.toml` — project metadata and dependencies
- `main.py` — FastAPI application with a simple route
- `.gitignore` — ignores Python build files and `.venv`

## How to start the app

1. Open a terminal in the project folder:

```bash
cd /home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend
```

2. Start the development server with `uv`:

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

3. Open your browser or API client to:

```text
http://127.0.0.1:8000/
```

## Notes

- `uv run` ensures the command runs inside the project-managed environment.
- `--reload` enables automatic server restart when code changes are saved.
- For production, remove `--reload` and consider running a dedicated process manager.
