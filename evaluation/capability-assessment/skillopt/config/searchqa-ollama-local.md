# SkillOpt local-gateway run recipe (SearchQA, Ollama) — reproducible record

The exact, reproducible recipe used for the verified runs. Points SkillOpt at
the **local Ollama gateway** (free, on-box, no external egress, no provider key).
Requires `PYTHONUTF8=1` on Windows.

## Environment (Ollama backend, both roles)

```
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
TARGET_OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1
TARGET_OPENAI_COMPATIBLE_API_KEY=ollama          # dummy; Ollama ignores it
TARGET_OPENAI_COMPATIBLE_MODEL=qwen3:8b
OPTIMIZER_OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1
OPTIMIZER_OPENAI_COMPATIBLE_API_KEY=ollama
OPTIMIZER_OPENAI_COMPATIBLE_MODEL=qwen3:8b
```

## One-time: materialize SearchQA (public HF, no auth)

```
uv pip install datasets
python scripts/materialize_searchqa.py       # -> data/searchqa_split (train=400/val=200/test=1400)
```

## Full-loop E2E (verified, EXIT=0) — tiny 6/3/3

Build a tiny split (subset items.json to 6/3/3, copy split_manifest.json) then:

```
python scripts/train.py --config configs/searchqa/default.yaml \
  --cfg-options \
    model.target_backend=openai_compatible model.optimizer_backend=openai_compatible \
    model.target=qwen3:8b model.optimizer=qwen3:8b \
    train.num_epochs=1 train.batch_size=3 train.train_size=6 \
    evaluation.sel_env_num=3 evaluation.test_env_num=3 evaluation.eval_test=true \
    env.split_dir=data/searchqa_tiny env.workers=2 \
  --out_root outputs/searchqa_tiny_run
```

Gotchas learned (see results.md):
- `train.train_size` MUST equal the loaded split size when `split_mode=split_dir`.
- `PYTHONUTF8=1` is mandatory on Windows (optimizer prints `->` etc.).
- `env.shuffle_choices` is a YAML bool; `--cfg-options env.shuffle_choices=false`
  passes the STRING "false" (truthy) and does NOT disable it — edit the config
  YAML for a real bool, or use a benchmark without choice-shuffling (searchqa).

## PILOT lift run (next; CAPABLE optimizer, full split) — operator-gated

Swap the optimizer to a capable model and use the full split:
`model.optimizer=<Sol/Claude/frontier>` (native SkillOpt backend or gateway
opt-in lane), drop the tiny-split overrides, keep `use_gate=true`. Record cost +
model on the run and put the result on `LEADERBOARD.md`.
