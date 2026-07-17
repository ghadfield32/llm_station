export const RESEARCH_ANALYSIS_SCHEMA_VERSION =
  "growthos.research-analysis.v5";

export type ResearchProjectFit = {
  project: string;
  fit_score: number;
  item_evidence: string;
  project_capability: string;
  why: string;
  suggested_application: string;
};

type ResearchCard = Record<string, unknown>;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.every((item) => typeof item === "string" && !!item.trim())
    ? value.map((item) => item.trim()) : [];
}

function validIsoDateTime(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(
    value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone] =
    match;
  const [year, month, day, hour, minute, second] = [
    yearText, monthText, dayText, hourText, minuteText, secondText,
  ].map(Number);
  const calendar = new Date(Date.UTC(year, month - 1, day));
  const zoneParts = zone === "Z" ? [0, 0] : zone.slice(1).split(":").map(Number);
  return (
    calendar.getUTCFullYear() === year
    && calendar.getUTCMonth() === month - 1
    && calendar.getUTCDate() === day
    && hour <= 23 && minute <= 59 && second <= 59
    && zoneParts[0] <= 23 && zoneParts[1] <= 59
    && !Number.isNaN(Date.parse(value))
  );
}

export function researchScore(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

export function researchProjectFits(card: ResearchCard): ResearchProjectFit[] {
  if (!Array.isArray(card.project_fits)) return [];
  return card.project_fits.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const row = value as Record<string, unknown>;
    const project = text(row.project);
    const fitScore = researchScore(row.fit_score);
    const itemEvidence = text(row.item_evidence);
    const projectCapability = text(row.project_capability);
    const why = text(row.why);
    const application = text(row.suggested_application);
    const exactKeys = [
      "fit_score", "item_evidence", "project", "project_capability",
      "suggested_application", "why",
    ];
    if (
      !project || project.length > 120
      || fitScore === null || fitScore < 0 || fitScore > 100
      || !itemEvidence || itemEvidence.length > 600
      || !projectCapability || projectCapability.length > 240
      || (projectCapability === "no direct match" && fitScore > 24)
      || !why || why.length > 600
      || !application || application.length > 600
      || Object.keys(row).sort().join("|") !== exactKeys.join("|")
    ) return [];
    return [{
      project, fit_score: fitScore, item_evidence: itemEvidence,
      project_capability: projectCapability, why,
      suggested_application: application,
    }];
  });
}

function derivedResearchPriority(card: ResearchCard): string | null {
  const relevance = researchScore(card.relevance_score);
  const impact = researchScore(card.potential_impact_score);
  const readiness = researchScore(card.implementation_readiness_score);
  const confidence = researchScore(card.evidence_confidence_score);
  if ([relevance, impact, readiness, confidence].some((value) => (
    value === null || value < 0 || value > 100
  ))) return null;
  const upside = Math.max(impact as number, readiness as number);
  if ((relevance as number) >= 75 && upside >= 70 && (confidence as number) >= 60) {
    return "high";
  }
  if ((relevance as number) >= 55 && upside >= 50 && (confidence as number) >= 50) {
    return "medium";
  }
  if ((relevance as number) >= 35 || upside >= 50) return "low";
  return "watch";
}

export function researchAnalysisComplete(
  card: ResearchCard, registeredProjects: string[] = [],
): boolean {
  const listLimits: Record<string, number> = {
    pros: 8, cons: 8, key_details: 12, implementation_notes: 12,
    work_areas: 8, use_cases: 8,
  };
  const scoreFields = [
    "relevance_score", "potential_impact_score",
    "implementation_readiness_score", "evidence_confidence_score",
    "best_project_fit_score",
  ];
  const fits = researchProjectFits(card);
  const fitNames = fits.map((fit) => fit.project);
  const expectedNames = Array.from(new Set(registeredProjects));
  const exactProjectCoverage = (
    expectedNames.length > 0
    && fits.length === expectedNames.length
    && new Set(fitNames).size === fits.length
    && expectedNames.every((project) => fitNames.includes(project))
  );
  const orderedFits = [...fits].sort(
    (left, right) => right.fit_score - left.fit_score
      || left.project.localeCompare(right.project));
  const expectedApplicable = orderedFits
    .filter((fit) => fit.fit_score >= 35).map((fit) => fit.project);
  const expectedSummary = orderedFits.map((fit) =>
    `- ${fit.project} · ${fit.fit_score}/100 — `
    + `Item evidence: ${fit.item_evidence} `
    + `Project capability: ${fit.project_capability}. Why: ${fit.why} `
    + `Suggested application: ${fit.suggested_application}`).join("\n");
  const generatedAt = card.analysis_generated_at;
  return (
    card.analysis_status === "complete"
    && card.analysis_schema_version === RESEARCH_ANALYSIS_SCHEMA_VERSION
    && card.analysis_origin === "local_model"
    && !!text(card.analysis_model)
    && (
      card.analysis_error_code === undefined
      || card.analysis_error_code === null
      || card.analysis_error_code === ""
    )
    && /^[0-9a-f]{64}$/.test(text(card.analysis_input_sha256))
    && validIsoDateTime(generatedAt)
    && !!text(card.useful_for_us)
    && text(card.useful_for_us).length <= 1200
    && ["high", "medium", "low", "watch"].includes(
      text(card.research_priority))
    && text(card.research_priority) === derivedResearchPriority(card)
    && ["small", "medium", "large", "research_only"].includes(
      text(card.estimated_effort))
    && Object.entries(listLimits).every(([field, maximum]) => {
      const values = stringList(card[field]);
      return values.length > 0 && values.length <= maximum
        && values.every((value) => value.length <= 1200);
    })
    && scoreFields.every((field) => {
      const score = researchScore(card[field]);
      return score !== null && score >= 0 && score <= 100;
    })
    && exactProjectCoverage
    && researchScore(card.relevance_score) === orderedFits[0]?.fit_score
    && card.best_project === orderedFits[0]?.project
    && researchScore(card.best_project_fit_score) === orderedFits[0]?.fit_score
    && Array.isArray(card.applicable_projects)
    && JSON.stringify(card.applicable_projects)
      === JSON.stringify(expectedApplicable)
    && card.project_fit_summary === expectedSummary
  );
}

export function researchDetailBadge(
  card: ResearchCard, registeredProjects: string[],
): { label: string; tone: string } {
  if (researchAnalysisComplete(card, registeredProjects)) {
    return { label: "Details complete", tone: "good" };
  }
  const status = text(card.analysis_status);
  if (status === "failed") return { label: "Analysis failed", tone: "bad" };
  if (status === "unavailable") {
    return { label: "Analysis unavailable", tone: "bad" };
  }
  if (status === "complete") return { label: "KPI upgrade pending", tone: "warn" };
  return { label: "Details pending", tone: "run" };
}
