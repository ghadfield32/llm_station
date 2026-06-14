---
okf_version: '0.1'
profile: growth-os-0.1
type: API
title: Chat-gateway agents (Discord/Slack/Telegram/WhatsApp)
description: The chat agents, their transports, enabled state, and model roles.
resource: config://configs/channels.yaml
tags:
- agents
- discord
- chat
- gateway
timestamp: '2026-06-14T03:44:07.529660+00:00'
last_verified_at: '2026-06-14T03:44:07.529660+00:00'
source_system: config
source_path: configs/channels.yaml
source_revision: null
source_hash: sha256:bb0ba885e63766c3fba83372d7681ef609ff264cd1757cb9f4f7f3c838e6d4b7
authority: derived
owner: command-center
status: current
sensitivity: internal
confidence: verified
generated_by: growthos-okf-producer
generator_version: 0.1.0
mission_id: null
experiment_id: null
supersedes: null
review_after: '2026-07-14T03:44:07.529660+00:00'
---

<!-- generated:start -->
Chat-gateway agents — every channel is one more SURFACE, not a new authority: messages
route through LiteLLM (local-first) to the same Growth OS action layer, and none can
approve a mission card.

| Channel | Transport | Enabled | Model |
|---|---|---|---|
| discord-main | discord | True | chat |
| slack-main | slack | False | chat |
| telegram-main | telegram | False | chat |
| whatsapp-main | whatsapp | False | chat |
| sms-main | sms | False | chat |
<!-- generated:end -->

## Human notes

_Add curated notes here; they are preserved across regenerations._
