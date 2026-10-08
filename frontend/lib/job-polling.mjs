export const STATUS_LABELS = {
  queued: "대기 중",
  running: "처리 중",
  validating: "설명 해석 중",
  searching: "레퍼런스 검색 중",
  rendering: "결과 정리 중",
  completed: "완료",
  failed: "처리 실패",
};

const TERMINAL = new Set(["completed", "failed"]);
const POLL_ERROR = "처리 상태를 불러오지 못했습니다. 잠시 후 새 요청으로 다시 시도해 주세요.";

export function pollDelay(value) {
  return Number.isFinite(value) && value > 0 ? value : 1000;
}

export function createJobPoller(jobId, options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const schedule = options.schedule || globalThis.setTimeout;
  const cancel = options.cancel || globalThis.clearTimeout;
  const controller = new AbortController();
  let stopped = false;
  let timer;

  async function tick() {
    if (stopped) return;
    try {
      const response = await fetchImpl(`/api/jobs/${encodeURIComponent(jobId)}`, {
        credentials: "include",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("job request failed");
      const job = await response.json();
      if (!Object.hasOwn(STATUS_LABELS, job?.job_status)) throw new Error("invalid job status");
      if (stopped) return;
      options.onUpdate(job);
      if (TERMINAL.has(job.job_status)) return;
      timer = schedule(tick, pollDelay(job.poll_after_ms));
    } catch {
      if (!stopped) options.onError(POLL_ERROR);
    }
  }

  return {
    start(delay) { timer = schedule(tick, pollDelay(delay)); },
    stop() {
      stopped = true;
      controller.abort();
      if (timer !== undefined) cancel(timer);
    },
  };
}
