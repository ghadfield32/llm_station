export type LoadResilienceState = {
  stale: boolean;
  staleSince: number | null;
  consecutiveFailures: number;
  lastError: string | null;
  bannerError: string | null;
};

export type LoadFailureOptions = {
  now?: number;
  quiet?: boolean;
};

const FETCH_KILL_MESSAGE =
  /(?:load failed|failed to fetch|networkerror|cancelled)/i;

export function createLoadResilienceState(): LoadResilienceState {
  return {
    stale: false,
    staleSince: null,
    consecutiveFailures: 0,
    lastError: null,
    bannerError: null,
  };
}

export function loadErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function isTransientLoadError(error: unknown): boolean {
  if (
    typeof error === "object" && error !== null &&
    "name" in error && error.name === "AbortError"
  ) {
    return true;
  }
  return error instanceof TypeError &&
    FETCH_KILL_MESSAGE.test(error.message);
}

export function recordLoadFailure(
  current: LoadResilienceState,
  error: unknown,
  options: LoadFailureOptions = {},
): LoadResilienceState {
  const consecutiveFailures = current.consecutiveFailures + 1;
  const message = loadErrorMessage(error);
  const showBanner = !options.quiet &&
    !isTransientLoadError(error) &&
    consecutiveFailures >= 2;
  return {
    stale: true,
    staleSince: current.staleSince ?? options.now ?? Date.now(),
    consecutiveFailures,
    lastError: message,
    bannerError: showBanner ? message : null,
  };
}

export function recordLoadSuccess(): LoadResilienceState {
  return createLoadResilienceState();
}
