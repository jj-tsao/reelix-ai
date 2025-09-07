.PHONY: help dev dev-web dev-api dev-worker

help:
	@echo "Targets: dev (turbo), dev-web, dev-api, dev-worker"

dev:
	@pnpm dev

dev-web:
	@cd apps/web && pnpm dev

dev-api:
	@echo "Run FastAPI app (requires uvicorn)"
	@echo "Example: uvicorn app.main:app --reload --port 8000 --app-dir apps/api"

dev-worker:
	@echo "Run scheduler worker (Python)"
	@echo "Example: python apps/scheduler-worker/worker/main.py"
