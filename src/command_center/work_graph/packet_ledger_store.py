"""LedgerPacketStore — durable sibling of packet.InMemoryPacketStore, backed by
the Ledger's /readiness-packet* endpoints. Same surface (the PacketStore
Protocol), so PacketService runs unchanged over either backend — mirroring
work_graph.ledger_store.LedgerWorkGraphStore.

Sync, injected httpx.Client; 404 → KeyError (the in-memory contract). The packet
row is upserted (INSERT OR REPLACE); revisions are append-only and immutable
(409 → PacketError); the CURRENT reviews live on the row (reviews_json) while
packet_reviews is the per-revision audit; packet_work_links is authoritative for
a committed packet's items (ReadinessPacket.work_item_ids is reconstructed from
it by the Ledger). A committed packet is frozen at the DB layer (409).
"""
from __future__ import annotations

from collections.abc import Sequence

import httpx

from .packet import PacketError, PacketRevision, ReadinessPacket


class LedgerPacketStore:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def add(self, packet: ReadinessPacket) -> None:
        self._put(packet)

    def put(self, packet: ReadinessPacket) -> None:
        self._put(packet)

    def _put(self, packet: ReadinessPacket) -> None:
        r = self._client.post("/readiness-packet",
                              json=packet.model_dump(mode="json"))
        r.raise_for_status()

    def get(self, packet_id: str) -> ReadinessPacket:
        r = self._client.get(f"/readiness-packet/{packet_id}")
        if r.status_code == 404:
            raise KeyError(f"no such packet: {packet_id}")
        r.raise_for_status()
        return ReadinessPacket(**r.json())

    def list(self, *, status: str | None = None) -> list[ReadinessPacket]:
        params = {"status": status} if status is not None else {}
        r = self._client.get("/readiness-packets", params=params)
        r.raise_for_status()
        return [ReadinessPacket(**d) for d in r.json()]

    def append_revision(self, packet_id: str, revision: int, content_digest: str,
                        snapshot_json: str, at: str) -> None:
        r = self._client.post(
            f"/readiness-packet/{packet_id}/revision",
            json={"revision": revision, "content_digest": content_digest,
                  "snapshot_json": snapshot_json, "created_at": at})
        if r.status_code == 409:                 # duplicate revision or frozen
            raise PacketError(_detail(r, f"revision {revision} rejected"))
        r.raise_for_status()

    def list_revisions(self, packet_id: str) -> list[PacketRevision]:
        r = self._client.get(f"/readiness-packet/{packet_id}/revisions")
        r.raise_for_status()
        return [PacketRevision(**d) for d in r.json()]

    def record_review(self, packet_id: str, revision: int, role: str, status: str,
                     summary: str, findings: Sequence[str],
                     session_id: str | None, at: str) -> None:
        r = self._client.post(
            f"/readiness-packet/{packet_id}/review",
            json={"revision": revision, "role": role, "status": status,
                  "summary": summary, "findings": list(findings),
                  "session_id": session_id, "reviewed_at": at})
        if r.status_code == 409:                 # committed → frozen
            raise PacketError(_detail(r, f"packet {packet_id} is frozen"))
        r.raise_for_status()

    def add_work_links(self, packet_id: str,
                       work_item_ids: Sequence[str]) -> None:
        r = self._client.post(f"/readiness-packet/{packet_id}/work-links",
                             json={"work_item_ids": list(work_item_ids)})
        r.raise_for_status()

    def work_links(self, packet_id: str) -> list[str]:
        r = self._client.get(f"/readiness-packet/{packet_id}/work-links")
        r.raise_for_status()
        return r.json()["work_item_ids"]

    def commit(self, packet: ReadinessPacket,
               work_item_ids: Sequence[str]) -> None:
        r = self._client.post(
            f"/readiness-packet/{packet.packet_id}/commit",
            json={"status": packet.status, "committed_at": packet.committed_at,
                  "updated_at": packet.updated_at,
                  "work_item_ids": list(work_item_ids)})
        if r.status_code == 404:
            raise KeyError(f"no such packet: {packet.packet_id}")
        if r.status_code == 409:                 # already committed
            raise PacketError(_detail(r, f"packet {packet.packet_id} committed"))
        r.raise_for_status()


def _detail(r: httpx.Response, fallback: str) -> str:
    try:
        return r.json().get("detail", fallback)
    except Exception:
        return fallback
