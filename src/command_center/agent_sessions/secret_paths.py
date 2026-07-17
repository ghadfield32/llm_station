"""Single source of truth for paths an agent session must never read.

Two walls share this denylist so a path that is secret in one place is secret
everywhere — no drift between them:

1. The OpenRouter adapter's read-only tools (egress teeth): a secret must never
   be read and shipped to a PAID EXTERNAL API.
2. The Home workspace sandbox (Phase 2): the user's whole home directory is a
   legitimate read-only context, but credential/secret locations under it must
   stay unreadable even there.

Matching is on path SEGMENTS (case-insensitive) and on filename SUFFIXES, so it
works for both repo-relative paths and absolute home-workspace paths.
"""
from __future__ import annotations

# Any path segment equal to one of these (case-insensitive) is secret. Covers
# credential dirs, SSH/cloud/GPG stores, and browser-profile roots that hold
# saved passwords/cookies. (The plan's denied list: .ssh .aws .azure .gnupg
# browser profiles .env files credential stores private key files.)
SECRET_SEGMENTS: frozenset[str] = frozenset({
    ".env", ".ssh", ".aws", ".azure", ".gnupg", ".git-credentials",
    "credentials", "secrets", "id_rsa", "id_ed25519",
    ".docker", ".kube", ".password-store", "keychains",
    # browser profiles (saved passwords, cookies, tokens)
    ".mozilla", ".thunderbird", "user data", "login data", "cookies",
})

# Filenames ending in one of these are secret (private keys, keystores, env).
SECRET_SUFFIXES: tuple[str, ...] = (
    ".pem", ".key", ".p12", ".pfx", ".ppk", ".keystore", ".jks", ".kdbx",
    ".env",
)


def is_secret_path(rel: str) -> bool:
    """True if `rel` (repo-relative or absolute) points at a credential/secret
    location. Segment- and suffix-based so it never depends on the CWD."""
    low = rel.replace("\\", "/").lower()
    if any(low.endswith(sfx) for sfx in SECRET_SUFFIXES):
        return True
    segs = set(low.split("/"))
    if segs & SECRET_SEGMENTS:
        return True
    # ".env", ".env.local", ".env.production" etc. as a filename
    name = low.rsplit("/", 1)[-1]
    return name == ".env" or name.startswith(".env.")
