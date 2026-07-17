FROM python:3.12-slim
WORKDIR /app
COPY growth_os/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY growth_os/ .
COPY src/command_center /app/command_center
CMD ["python", "-m", "growthos.watcher"]
