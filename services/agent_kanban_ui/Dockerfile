# Multi-stage: build the SPA with node, then serve it + the cockpit API with
# python. Build context is the REPO ROOT (compose sets it) so we can pull src/ for
# the single-source command_center.kanban.metrics. The package is stdlib-only along
# the import path used here, so PYTHONPATH is enough — no pip install of the package.

# --- stage 1: build the React/Vite SPA -------------------------------------
FROM node:20-slim AS web
WORKDIR /web
COPY services/agent_kanban_ui/web/package*.json ./
RUN npm ci
COPY services/agent_kanban_ui/web/ ./
RUN npm run build

# --- stage 2: serve --------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
COPY services/agent_kanban_ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ /app/src/
COPY services/agent_kanban_ui/app.py /app/app.py
COPY services/agent_kanban_ui/agent_worker_client.py /app/agent_worker_client.py
COPY services/agent_kanban_ui/domain_fixtures.json /app/domain_fixtures.json
COPY --from=web /web/dist /app/static
ENV PYTHONPATH=/app/src KANBAN_UI_STATIC=/app/static
EXPOSE 8787
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8787"]
