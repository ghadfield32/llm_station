# Tiny image that carries the command_center package so the control plane can
# render its own LiteLLM config inside Docker — no host Python / make required.
# Used by the `config-render` one-shot service in docker-compose.yml, which runs
# before litellm and writes generated/litellm-config.yaml into the shared bind mount.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
WORKDIR /work
# registry.render reads configs/ and writes generated/ relative to the CWD (/work),
# both bind-mounted by the service. Overridable; this is the default job.
ENTRYPOINT ["python", "-m", "command_center.registry.render"]
