# Install on WSL2 (Ubuntu)

WSL2 gives you Linux semantics (bash, GNU Make, Airflow) while sharing the
Windows host's Docker + Ollama.

## 1. Prerequisites

- **WSL2 + Ubuntu** (`wsl --install -d Ubuntu` from an elevated PowerShell).
- **Docker Desktop** with WSL2 integration enabled for the distro (Settings ->
  Resources -> WSL integration), so `docker` works inside WSL.
- **[uv](https://docs.astral.sh/uv/)**: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **git**, **openssl**, **make** (`sudo apt install -y git openssl make`).
- **Ollama**: either run Ollama on the Windows host and point WSL at it, or
  install Ollama inside WSL.

## 2. Clone + preflight

```bash
git clone --recurse-submodules https://github.com/ghadfield32/llm_station.git
cd llm_station
uv run cc doctor
```

## 3. First boot

```bash
uv run cc init-env
# Point at the host's Ollama if it runs on Windows:
#   set OLLAMA_API_BASE in .env to http://host.docker.internal:11434 (or the host IP)
uv run cc models-light
uv run cc start
uv run cc live-smoke
```

`make first-boot` is the GNU Make equivalent of `cc start` if you prefer Make.

## 4. Airflow (daily self-improvement)

WSL is the convenient place to run the daily DAG (`dags/self_improvement_daily.py`):

```bash
airflow dags list
airflow dags test self_improvement_daily $(date +%F)
# or run the command directly on a cron:
uv run cc self-improvement-daily --draft-kanban true --apply false
```

The DAG is observer/draft-only — see
[RUNNING_DAILY_SELF_IMPROVEMENT.md](../operations/RUNNING_DAILY_SELF_IMPROVEMENT.md).

## 5. Notes

- Keep the repo on the **Linux filesystem** (`~/…`), not `/mnt/c/…`, for sane
  file-watching and performance.
- Same local-only contract: no provider keys in `.env`.
- Continue at [GETTING_STARTED.md](GETTING_STARTED.md) §3.
