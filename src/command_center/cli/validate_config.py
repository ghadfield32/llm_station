#!/usr/bin/env python3
"""
validate_config.py — load every configs/*.yaml through its Pydantic contract.

Exit 0 = all valid. Exit 1 = a typo'd key, bad value, or broken invariant
(e.g. L3 without approval, a repo_task holding secrets, duplicate priorities).
This is the "hard to break" guarantee: bad config fails here, not at 2am.
"""
import sys
import yaml
from pydantic import ValidationError

from command_center.schemas import CONFIG_CONTRACTS


def main() -> int:
    ok = True
    for path, contract in CONFIG_CONTRACTS.items():
        try:
            data = yaml.safe_load(open(path))
            contract.model_validate(data)
            print(f"  OK   {path}  ({contract.__name__})")
        except FileNotFoundError:
            print(f"  MISS {path}  (not found)")
            ok = False
        except ValidationError as e:
            print(f"  FAIL {path}")
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                print(f"         {loc}: {err['msg']}")
            ok = False
        except Exception as e:
            print(f"  FAIL {path}: {e}")
            ok = False
    print("validate: PASS" if ok else "validate: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
