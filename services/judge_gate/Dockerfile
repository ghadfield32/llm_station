FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py judgectl.py ./
# make `judgectl` callable inside the container and from `docker compose exec`
RUN printf '#!/usr/bin/env bash\nexec python3 /app/judgectl.py "$@"\n' > /usr/local/bin/judgectl \
    && chmod +x /usr/local/bin/judgectl
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
EXPOSE 8088
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8088"]
