export type AgentSessionInstructionsSource = "inline" | "file";

/**
 * Redacted read shape consumed by the cockpit chrome.
 *
 * AGT-10's future allocator emits validated AgentSessionSpec YAML into the
 * shared spec directory; this is the display contract that emission joins.
 * It intentionally has no instruction body, credential, or session-mutation
 * field.
 */
export interface AgentSessionSpecSummary {
  name: string;
  harness: string;
  capability_profile: string;
  effort: string | null;
  mode: string;
  instructions_source: AgentSessionInstructionsSource;
  policy_refs: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** Parse only display-safe, valid entries; typed API errors degrade to no option. */
export function parseAgentSessionSpecs(payload: unknown): AgentSessionSpecSummary[] {
  if (!Array.isArray(payload)) return [];
  const specs: AgentSessionSpecSummary[] = [];
  for (const entry of payload) {
    if (!isRecord(entry) || "error" in entry) continue;
    if (!isNonEmptyString(entry.name)
      || !isNonEmptyString(entry.harness)
      || !isNonEmptyString(entry.capability_profile)
      || !isNonEmptyString(entry.mode)
      || (entry.effort !== null && !isNonEmptyString(entry.effort))
      || (entry.instructions_source !== "inline" && entry.instructions_source !== "file")
      || !Array.isArray(entry.policy_refs)
      || !entry.policy_refs.every(isNonEmptyString)) {
      continue;
    }
    specs.push({
      name: entry.name,
      harness: entry.harness,
      capability_profile: entry.capability_profile,
      effort: entry.effort,
      mode: entry.mode,
      instructions_source: entry.instructions_source,
      policy_refs: [...entry.policy_refs],
    });
  }
  return specs;
}

export function agentSessionSpecOptionLabel(spec: AgentSessionSpecSummary): string {
  return `${spec.name} — ${spec.harness} · ${spec.capability_profile}`;
}
