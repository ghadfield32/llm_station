export type ResearchSource = "paper" | "repo";
export type ResearchCounts = {
  total: number;
  titled: number;
  complete: number;
  pending: number;
  missing_title: number;
};
export function exactResearchProgressCounts(
  exact: ResearchCounts,
): ResearchCounts {
  const total = Math.max(0, Math.trunc(exact.total));
  const titled = Math.min(total, Math.max(0, Math.trunc(exact.titled)));
  const complete = Math.min(titled, Math.max(0, Math.trunc(exact.complete)));
  return {
    total,
    titled,
    complete,
    pending: titled - complete,
    missing_title: total - titled,
  };
}
