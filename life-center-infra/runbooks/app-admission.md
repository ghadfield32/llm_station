# Per-application admission checklist

Adopt **one authoritative application per category**. A service stays a
replaceable candidate until it passes this gate. Do not run overlapping
applications just because they are available. No real personal data is admitted
until the applicable [`LIFE_CENTER_SECURITY_BASELINE.md`](../../docs/operations/LIFE_CENTER_SECURITY_BASELINE.md)
gates (G0–G6) pass.

## Gate (all must pass before real data)

- [ ] **Import** — representative dummy data imports cleanly.
- [ ] **Backup** — application-consistent export runs (not just a volume copy).
- [ ] **Restore** — export restores into a clean, version-matched instance.
- [ ] **Upgrade** — image bump applies without data loss (test on dummy data).
- [ ] **Rollback** — previous version + snapshot restores after a failed upgrade.
- [ ] **Export** — portable data export exists (no lock-in).
- [ ] **Client access** — native/browser client reaches it over Tailscale.
- [ ] **Hardening** — loopback-bound, image digest-pinned, secrets from `.env`
      (not defaults), no public exposure.
- [ ] **Board redaction** — the cockpit surface shows only health/freshness, never
      contents (see the plan's Dashboard & Kanban rules).

## Admission order (from the plan)

1. host / storage / network + one backup engine
2. Nextcloud (dummy files) → Joplin migration pilot
3. Immich (dummy photos)
4. Paperless (dummy records)
5. one task system
6. Linkwarden / FreshRSS / Mealie / Homebox / Stirling-PDF — one at a time
7. Jellyfin / books
8. AdGuard (with tested fallback DNS)
9. Home Assistant OS (isolated VM/device)
10. Actual (after the sensitive-data gate)
11. read-only Command Center boards
12. password manager (last)

## Per-tier notes

- **files/photos/docs** — carry irreplaceable-adjacent data; restore proof is
  mandatory before real content.
- **network (AdGuard)** — needs a tested bypass/fallback before it becomes the
  household resolver.
- **smart-home (Home Assistant)** — production form is an isolated VM/device, not
  the convenience container in `compose/smart-home.yml`.
- **vault** — admitted last; prefer official Bitwarden; complete offline recovery
  test before migrating a real vault.
- **Open Design** — dev-lane only; its gate is agent-detect + a BYOK generation
  smoke test + `.od/` export/clean-restore. Not an appliance profile.
