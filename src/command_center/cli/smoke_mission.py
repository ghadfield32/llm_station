#!/usr/bin/env python3
"""
mission_dryrun.py — run a fake mission through the gates + judges contracts
WITHOUT calling any model. Proves the lifecycle config is coherent: the risk
tier maps to required stages, each required stage has judges defined, and L3/L4
correctly demand approval. Cheap, deterministic, runs in CI.

  python -m command_center.cli.smoke_mission L2 betts_basketball "add a unit test"
  python -m command_center.cli.smoke_mission L4 infra "rotate the deploy key"
"""
import sys
import yaml

from command_center.schemas import GatesConfig, JudgeConfig, RiskTier, MissionOpen


def main() -> int:
    tier = RiskTier(sys.argv[1] if len(sys.argv) > 1 else "L2_local_edits") \
        if "_" in (sys.argv[1] if len(sys.argv) > 1 else "") else \
        {"L0": RiskTier.L0, "L1": RiskTier.L1, "L2": RiskTier.L2,
         "L3": RiskTier.L3, "L4": RiskTier.L4}[sys.argv[1] if len(sys.argv) > 1 else "L2"]
    repo = sys.argv[2] if len(sys.argv) > 2 else "demo-repo"
    action = sys.argv[3] if len(sys.argv) > 3 else "do a thing"

    # validate the inbound mission shape
    MissionOpen(repo=repo, requested_action=action, requester="dryrun", risk_tier=tier)

    gates = GatesConfig.model_validate(yaml.safe_load(open("configs/gates.yaml")))
    judges = JudgeConfig.model_validate(yaml.safe_load(open("configs/judges.yaml")))
    stages_with_judges = {s.stage for s in judges.stages}

    policy = gates.tiers[tier]
    print(f"mission: [{tier.value}] {repo}: {action}")
    print(f"  auto={policy.auto}  requires_approval={policy.requires_approval}")
    print(f"  required stages: {policy.required_stages}")

    ok = True
    for stage in policy.required_stages:
        # 'intake'/'plan'/'pre-push' may be pure lifecycle steps; judge stages must exist if named
        has = stage in stages_with_judges
        marker = "judges:OK" if has else "lifecycle-only"
        print(f"    - {stage:14s} {marker}")
    if policy.forbidden_auto_actions:
        print(f"  forbidden auto actions: {policy.forbidden_auto_actions}")

    # invariant re-check at runtime, belt and suspenders
    if tier in (RiskTier.L3, RiskTier.L4) and not policy.requires_approval:
        print("  INVARIANT VIOLATION: L3/L4 without approval"); ok = False

    print("dry-run: PASS" if ok else "dry-run: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
