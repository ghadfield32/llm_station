"""AppFlowy Cloud client. Auth via GoTrue (email/password -> token), then
row upserts against the database REST API. Includes a DRY-RUN mode that
writes importable CSVs instead of live rows.

The live write path is VERIFIED against self-hosted AppFlowy Cloud (2026-06):
  login : POST {base}/gotrue/token?grant_type=password   -> access_token
  upsert: PUT  {base}/api/workspace/{ws}/database/{db}/row
          {"pre_hash": <stable external id>, "cells": {<field_id>: value}}
          -> server hashes pre_hash into the row id, so re-sending the same
             item UPDATES it instead of duplicating (idempotent by design).

Database ids and field name->id mappings come from config/databases.json,
which scripts/setup_workspace.py generates when it creates the databases.
Cells are keyed by FIELD ID on the wire; this client resolves the human
field names used in FIELD_MAP. Select values must match an existing option
name; date fields accept ISO strings; lists are joined into text.
"""
from __future__ import annotations
import csv
import json
import logging
from pathlib import Path
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import CuratedItem

log = logging.getLogger("growthos.appflowy")

# Maps a CuratedItem -> the AppFlowy field names defined in config/schema.yaml.
FIELD_MAP = {
    "papers": lambda i: {
        "Title": i.title, "Authors": i.authors, "ArxivID": i.external_id,
        "Abstract": i.summary, "Suggested": i.extra.get("suggested", ""),
        "URL": i.url, "Topics": i.topics,
        "Score": i.score, "Status": "Inbox",
        "Published": i.published.isoformat() if i.published else "",
    },
    "repos": lambda i: {
        "Name": i.title, "Owner": i.extra.get("owner", ""), "URL": i.url,
        "Stars": i.extra.get("stars", 0), "Language": i.extra.get("language", ""),
        "Why": i.summary, "Suggested": i.extra.get("suggested", ""),
        "Topics": i.topics, "Score": i.score, "Status": "Inbox",
        "Updated": i.published.isoformat() if i.published else "",
    },
    "signals": lambda i: {
        "Headline": i.title, "Source": i.source, "URL": i.url,
        "Suggested": i.extra.get("suggested", ""),
        "Category": i.extra.get("category", "Other"), "Score": i.score,
        "Status": "Inbox",
        "Published": i.published.isoformat() if i.published else "",
    },
}
KIND_TO_DB = {"paper": "papers", "repo": "repos", "signal": "signals"}

DB_MAP_PATH = Path("config/databases.json")


class AppFlowyClient:
    ENDPOINTS = {
        "login": "/gotrue/token?grant_type=password",
        "workspaces": "/api/workspace",
        "databases": "/api/workspace/{ws}/database",
        "fields": "/api/workspace/{ws}/database/{db}/fields",
        "rows": "/api/workspace/{ws}/database/{db}/row",
        "row_detail": "/api/workspace/{ws}/database/{db}/row/detail",
        "rows_updated": "/api/workspace/{ws}/database/{db}/row/updated",
    }

    def __init__(self, base_url: str, workspace_id: str = "", token: str = "",
                 dry_run: bool = True, out_dir: str = "./_export",
                 db_map_path: Path | str = DB_MAP_PATH):
        self.base = base_url.rstrip("/")
        self.ws = workspace_id
        self.token = token
        self.dry_run = dry_run
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(timeout=30)
        self._db_map_path = Path(db_map_path)
        self._db_map: dict | None = None

    # ----- auth -----
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def login(self, email: str, password: str) -> None:
        if self.dry_run:
            log.info("dry-run: skipping AppFlowy login")
            return
        url = self.base + self.ENDPOINTS["login"]
        r = self._client.post(url, json={"email": email, "password": password})
        r.raise_for_status()
        self.token = r.json().get("access_token", "")
        if not self.token:
            raise RuntimeError("login returned no access_token")

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    # ----- database / field mapping (from setup_workspace.py) -----
    def db_entry(self, db_name: str) -> dict:
        if self._db_map is None:
            if not self._db_map_path.exists():
                raise RuntimeError(
                    f"{self._db_map_path} not found - run scripts/setup_workspace.py first")
            self._db_map = json.loads(self._db_map_path.read_text())
        if db_name not in self._db_map:
            raise RuntimeError(f"database '{db_name}' not in {self._db_map_path}")
        return self._db_map[db_name]

    @staticmethod
    def _wire_value(v):
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return v

    def _to_wire_cells(self, db_name: str, cells: dict) -> dict:
        """Translate {field_name: value} -> {field_id: value}, dropping empties
        (writing "" to date/select fields is at best a no-op) and unknown names."""
        fields = self.db_entry(db_name)["fields"]
        wire = {}
        for name, value in cells.items():
            value = self._wire_value(value)
            if value is None or value == "":
                continue
            fid = fields.get(name)
            if not fid:
                log.warning("%s: no field named %r in AppFlowy, skipping", db_name, name)
                continue
            wire[fid] = value
        return wire

    # ----- reads -----
    def list_row_ids(self, db_name: str) -> list[str]:
        e = self.db_entry(db_name)
        url = self.base + self.ENDPOINTS["rows"].format(ws=self.ws, db=e["database_id"])
        r = self._client.get(url, headers=self._headers)
        r.raise_for_status()
        return [x["id"] for x in r.json()["data"]]

    def row_details(self, db_name: str, row_ids: list[str], chunk: int = 40) -> list[dict]:
        """Row cells keyed by field NAME (the server resolves names on read)."""
        e = self.db_entry(db_name)
        url = self.base + self.ENDPOINTS["row_detail"].format(ws=self.ws, db=e["database_id"])
        out = []
        for i in range(0, len(row_ids), chunk):
            r = self._client.get(url, headers=self._headers,
                                 params={"ids": ",".join(row_ids[i:i + chunk])})
            r.raise_for_status()
            out += r.json()["data"]
        return out

    def rows_updated_since(self, db_name: str, after_iso: str) -> list[str]:
        e = self.db_entry(db_name)
        url = self.base + self.ENDPOINTS["rows_updated"].format(ws=self.ws, db=e["database_id"])
        r = self._client.get(url, headers=self._headers, params={"after": after_iso})
        r.raise_for_status()
        return [x["row_id"] for x in r.json()["data"]]

    # ----- writes -----
    def upsert(self, db_name: str, rows: list[dict]) -> list[str]:
        """Upsert rows shaped {"pre_hash": <stable id>, "cells": {name: value}}.
        Returns the pre_hashes that were actually written, so callers can mark
        ONLY successes as seen — a failed write (e.g. server briefly down) must
        stay eligible for retry on the next run. One bad row is logged and
        skipped, not fatal."""
        if self.dry_run:
            return self._write_csv(db_name, rows)
        e = self.db_entry(db_name)
        url = self.base + self.ENDPOINTS["rows"].format(ws=self.ws, db=e["database_id"])
        ok: list[str] = []
        for row in rows:
            cells = self._to_wire_cells(db_name, row["cells"])
            try:
                r = self._client.put(url, headers=self._headers,
                                     json={"pre_hash": row["pre_hash"], "cells": cells,
                                           "document": row.get("document")})
                r.raise_for_status()
                body = r.json()
                if body.get("code") != 0:
                    raise RuntimeError(body.get("message"))
                ok.append(row["pre_hash"])
            except Exception as exc:  # keep going; one bad row shouldn't kill the run
                title = row["cells"].get("Title") or row["cells"].get("Headline") or row["pre_hash"]
                log.warning("row write failed (%s): %s", title, exc)
        return ok

    def _write_csv(self, db_name: str, rows: list[dict]) -> list[str]:
        if not rows:
            return []
        path = self.out / f"{db_name}.csv"
        fields = list(rows[0]["cells"].keys())
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if new:
                w.writeheader()
            for row in rows:
                w.writerow({k: self._wire_value(v) for k, v in row["cells"].items()})
        log.info("dry-run: wrote %d rows -> %s", len(rows), path)
        return [r["pre_hash"] for r in rows]


def items_to_cells(items: list[CuratedItem]) -> dict[str, list[dict]]:
    """Bucket CuratedItems by target database; each row carries the item's
    external_id as pre_hash so live writes are idempotent server-side."""
    out: dict[str, list[dict]] = {}
    for it in items:
        db = KIND_TO_DB[it.kind]
        out.setdefault(db, []).append(
            {"pre_hash": it.external_id, "cells": FIELD_MAP[db](it)})
    return out
