FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
# proactive.yaml is mounted read-only from the repo at runtime (see compose).
# Invoked on a schedule (host cron / systemd timer / compose `restart` cron sidecar).
CMD ["python3", "app.py"]
