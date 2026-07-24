export type IntakeAnswers = {
  objective: string;
  research: string;
  kpis: string;
  plan: string;
  openQuestions: string;
};

function answerText(value: string): string {
  return value.trim() || "_Not answered yet._";
}

export function buildRunDocDraft(
  answers: IntakeAnswers,
  title: string,
  itemId: string,
): string {
  const runDocTitle = title.trim() || "Untitled project";
  const runDocItemId = itemId.trim() || "UNASSIGNED";

  return [
    `# RUNDOC — ${runDocItemId} · ${runDocTitle}`,
    "",
    "Through the `TODO_PROCESS.md` loop.",
    "",
    "## 1. Objective & definition of done",
    "",
    answerText(answers.objective),
    "",
    "## 2. Research",
    "",
    answerText(answers.research),
    "",
    "## 3. KPIs & baseline",
    "",
    answerText(answers.kpis),
    "",
    "## 4. Plan (bounded)",
    "",
    answerText(answers.plan),
    "",
    "## 5. Open questions / decisions",
    "",
    answerText(answers.openQuestions),
    "",
  ].join("\n");
}
