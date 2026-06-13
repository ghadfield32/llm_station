#!/usr/bin/env python3
"""
run_evals.py — regression-test the command center's routing policy.

This does NOT call models. It checks each eval case's *expected* behavior against
the gates contract: an L4 case must map to a tier that's non-auto and approval-
required; an L3 case the same; expected/forbidden stages must be consistent with
the tier's required_stages. This is the deterministic core of the promotion gate —
the live-model behavioral eval runs on top of this at install, but the policy
contract is checkable here, now, with no spend.

Exit 0 = every case's assertions are consistent with gates.yaml.
"""
import sys
import yaml
from command_center.schemas import EvalsConfig, GatesConfig

def main() -> int:
    evals = EvalsConfig.model_validate(yaml.safe_load(open("configs/evals.yaml")))
    gates = GatesConfig.model_validate(yaml.safe_load(open("configs/gates.yaml")))
    tiers = gates.tiers

    ok = True
    for c in evals.cases:
        tier = tiers.get(c.expected_risk.value)
        if tier is None:
            print(f"  FAIL {c.name}: expected_risk {c.expected_risk} not in gates.yaml"); ok = False; continue
        # L3/L4 cases must land on a non-auto, approval-required tier
        if c.expected_risk.value in ("L3_external_write", "L4_dangerous"):
            if tier.auto or not tier.requires_approval:
                print(f"  FAIL {c.name}: {c.expected_risk} tier must be non-auto + approval-required"); ok = False; continue
            if c.expected_auto_allowed is True:
                print(f"  FAIL {c.name}: asserts auto allowed for a gated tier"); ok = False; continue
        # forbidden stages must not be in the tier's required stages
        bad = set(c.forbidden_stages) & set(tier.required_stages)
        if bad:
            print(f"  FAIL {c.name}: forbids stage(s) {sorted(bad)} that the tier requires"); ok = False; continue
        print(f"  OK   {c.name}  ({c.expected_risk.value})")
    print("evals: PASS" if ok else "evals: FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
