#!/usr/bin/env python3
"""Emit JSON Schema for each config contract -> generated/json-schema/.
Useful for editor autocomplete/validation on the YAML files."""
import json
import os
from command_center.schemas import CONFIG_CONTRACTS

os.makedirs("generated/json-schema", exist_ok=True)
for path, contract in CONFIG_CONTRACTS.items():
    name = os.path.basename(path).replace(".yaml", ".schema.json")
    out = f"generated/json-schema/{name}"
    open(out, "w").write(json.dumps(contract.model_json_schema(), indent=2))
    print(f"wrote {out}")
