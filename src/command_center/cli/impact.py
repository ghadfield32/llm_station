#!/usr/bin/env python3
"""
impact.py — "what breaks if I change this?"

Reads your staged+unstaged git diff (or an explicit file list), looks each path
up in configs/breakage.yaml, and prints the blast radius + the checks you must
run before trusting the change. This is the piece that makes the system
understandable six months later.

Usage:
  python -m command_center.cli.impact            # uses `git diff --name-only HEAD`
  python -m command_center.cli.impact file1 file2
"""
import sys
import subprocess
import fnmatch
import yaml

BREAKAGE = "configs/breakage.yaml"


def changed_files() -> list[str]:
    if len(sys.argv) > 1:
        return sys.argv[1:]

    has_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    ).returncode == 0

    commands = [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    if has_head:
        commands.insert(0, ["git", "diff", "--name-only", "HEAD"])

    files: set[str] = set()
    for command in commands:
        out = subprocess.run(command, capture_output=True, text=True)
        if out.returncode == 0:
            files.update(ln for ln in out.stdout.splitlines() if ln.strip())
    return sorted(files)


def main() -> int:
    rules = yaml.safe_load(open(BREAKAGE))["changes"]
    files = changed_files()
    if not files:
        print("no changes detected")
        return 0

    matched = False
    for f in files:
        rule = rules.get(f)
        if rule is None:
            # allow glob keys like "schemas/*.py"
            for pat, r in rules.items():
                if fnmatch.fnmatch(f, pat):
                    rule = r
                    break
        if rule is None:
            print(f"\n• {f}\n    (no declared impact — review manually)")
            continue
        matched = True
        print(f"\n• {f}")
        print(f"    affects:  {', '.join(rule.get('affects', []))}")
        print(f"    run:      {' ; '.join(rule.get('required_checks', []))}")
        if rule.get("rollout"):
            print(f"    rollout:  {' -> '.join(rule['rollout'])}")
    if not matched:
        print("\n(no files with declared impact)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
