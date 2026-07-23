export type RuntimeKind = "gateway" | "claude" | "codex" | "agent";

export type RuntimeTarget = string | {
  harness_id: string;
  label?: string;
};

export type RuntimePresentation = {
  id: string;
  label: string;
  kind: RuntimeKind;
};

export type ChatEventPresentation =
  | { kind: "message"; role: "user" | "assistant"; text: string;
      collapsedDetail?: never }
  | { kind: "activity"; role: "assistant" | "system"; text: string;
      collapsedDetail?: string }
  | { kind: "error"; role: "assistant"; text: string;
      collapsedDetail?: string };

type ChatEventLike = {
  type?: unknown;
  content?: unknown;
  message?: unknown;
  detail?: unknown;
  n?: unknown;
  name?: unknown;
  args?: unknown;
  result?: unknown;
};

function readableHarnessName(id: string): string {
  return id
    .replace(/^agent:/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function runtimeLabel(target: RuntimeTarget): RuntimePresentation {
  const rawId = typeof target === "string" ? target : target.harness_id;
  const harnessId = rawId.replace(/^agent:/, "");
  if (!rawId || rawId === "GatewayCore" || rawId === "gateway") {
    return { id: "GatewayCore", label: "GatewayCore", kind: "gateway" };
  }

  const suppliedLabel = typeof target === "string" ? "" : target.label?.trim() ?? "";
  const identity = `${harnessId} ${suppliedLabel}`.toLowerCase();
  if (identity.includes("claude")) {
    return {
      id: harnessId,
      label: suppliedLabel || "Claude Code",
      kind: "claude",
    };
  }
  if (identity.includes("codex")) {
    return {
      id: harnessId,
      label: suppliedLabel || "Codex",
      kind: "codex",
    };
  }
  return {
    id: harnessId,
    label: suppliedLabel || readableHarnessName(harnessId) || "Agent",
    kind: "agent",
  };
}

function textValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(textValue).filter(Boolean).join(", ");
  return "";
}

function toolArguments(value: unknown): string {
  if (typeof value !== "string") {
    if (value && typeof value === "object") {
      return Object.values(value).map(textValue).filter(Boolean).join(", ");
    }
    return textValue(value);
  }
  try {
    const parsed = JSON.parse(value);
    if (parsed && typeof parsed === "object") {
      return Object.values(parsed).map(textValue).filter(Boolean).join(", ");
    }
  } catch {
    // A plain command or argument string is already suitable collapsed detail.
  }
  return value;
}

export function describeChatEvent(ev: ChatEventLike): ChatEventPresentation {
  const type = textValue(ev.type) || "unknown";
  switch (type) {
    case "you":
      return { kind: "message", role: "user", text: textValue(ev.content) };
    case "history":
    case "final":
      return { kind: "message", role: "assistant", text: textValue(ev.content) };
    case "error":
      return {
        kind: "error",
        role: "assistant",
        text: textValue(ev.message ?? ev.detail) || "Runtime error",
      };
    case "round":
      return {
        kind: "activity",
        role: "system",
        text: `round ${textValue(ev.n) || "?"}`,
      };
    case "tool":
      return {
        kind: "activity",
        role: "assistant",
        text: `tool: ${textValue(ev.name) || "tool"}`,
        collapsedDetail: toolArguments(ev.args) || "(no arguments)",
      };
    case "tool_result":
      return {
        kind: "activity",
        role: "assistant",
        text: `result: ${textValue(ev.name) || "tool"}`,
        collapsedDetail: textValue(ev.result) || "(empty result)",
      };
    default:
      return {
        kind: "activity",
        role: "system",
        text: `activity: ${type}`,
        collapsedDetail:
          "Unrecognized runtime event payload was withheld from the chat transcript.",
      };
  }
}

export function optionLabel(model: string): { label: string; title: string } {
  const full = model.trim();
  const separator = full.indexOf(" — ");
  return {
    label: separator >= 0 ? full.slice(0, separator).trim() : full,
    title: full,
  };
}
