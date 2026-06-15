SHELL := /bin/bash
API := apps/api
WEB := apps/web

.PHONY: dev api worker web seed install

install:
	cd $(API) && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd $(WEB) && npm install

api:
	cd $(API) && .venv/bin/uvicorn app.main:app --reload --port 8000

worker:
	cd $(API) && .venv/bin/python -m app.worker

web:
	cd $(WEB) && npx next dev --port 3000

seed:
	cd $(API) && .venv/bin/python seed_demo.py

# All three processes with one command (Ctrl-C stops everything)
dev:
	trap 'kill 0' EXIT; \
	(cd $(API) && .venv/bin/uvicorn app.main:app --reload --port 8000) & \
	(cd $(API) && .venv/bin/python -m app.worker) & \
	(cd $(WEB) && npx next dev --port 3000) & \
	wait
