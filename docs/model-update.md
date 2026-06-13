# Updating models

Models are data in `configs/models.yaml`. In the corrected setup, model roles are local-only:
every role must use `provider: ollama`, `local: true`, and render to `ollama_chat/...`.

## Safe Rollout

```
1. make model-scout
   -> writes generated/model-scout-report.md
2. Edit configs/models.yaml with a local Ollama candidate
3. make validate
4. make evals
5. make models-canary ROLE=planner MODEL=ollama_chat/<local-tag>
6. make live-smoke
7. make models-promote ROLE=planner or make models-rollback ROLE=planner
```

The contract rejects provider routes in LiteLLM roles. OpenAI, Anthropic, and OpenRouter
models are not valid LiteLLM deployments in this architecture.

## Current Local Picks

- `qwen3-coder:30b`
- `qwen3:30b`
- `devstral:24b`

The 4090/Ollama path is the cost lever. Claude Code and Codex remain outside LiteLLM as
subscription-authenticated executors.
