# Install on Windows (native)

The portable `uv run cc` driver works on native Windows (PowerShell). No GNU Make
required.

## 1. Prerequisites

- **Docker Desktop** (WSL2 backend recommended) — the control-plane services run here.
- **[uv](https://docs.astral.sh/uv/)** — `winget install astral-sh.uv` (or the install script).
- **Ollama** for Windows — the local model engine, runs on the host.
- **git** — `winget install Git.Git`.
- **OpenSSL** on PATH — used to sign the GitHub App JWT (Git for Windows ships it).

## 2. Clone + preflight

```powershell
git clone --recurse-submodules https://github.com/ghadfield32/llm_station.git
cd llm_station
uv run cc doctor
```

Fix anything `cc doctor` flags (it gives the exact next command).

## 3. First boot

```powershell
uv run cc init-env       # creates .env; OLLAMA_API_BASE default http://host.docker.internal:11434 is fine
uv run cc models-light   # pull qwen3:8b (~5 GB); big GPU? `uv run cc models`
uv run cc start          # doctor -> build -> up -> health -> opens the dashboards
uv run cc live-smoke     # real local replies through Ollama -> LiteLLM
```

`.\scripts\cc.ps1 <target>` is an alternative driver if you prefer; `uv run cc`
is recommended (identical operations, zero install).

## 4. Notes specific to Windows

- Run commands from the **repo root** (the config CLIs read `configs/` relative
  to the CWD).
- Do **not** add OpenAI/Anthropic keys to `.env` — local-only by contract;
  `cc validate` fails on provider keys.
- Daily self-improvement can be scheduled with `schtasks` running
  `uv run cc self-improvement-daily --draft-kanban true --apply false`.
- Continue at [GETTING_STARTED.md](GETTING_STARTED.md) §3.

Prefer Linux semantics / Airflow? See [INSTALL_WSL.md](INSTALL_WSL.md).
