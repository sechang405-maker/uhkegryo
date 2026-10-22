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
const POLL_ERROR = "처리 상태를 불러오지 못했습니다. 연결을 확인한 뒤 상태 다시 확인을 눌러 주세요.";

const AUTO_RETRY_LIMIT = 2;

function requestError(retryable) {
  const error = new Error("job request failed");
  error.retryable = retryable;
  return error;
}

function retryDelay(attempt) {
  return Math.min(500 * (2 ** (attempt - 1)), 2000);
}

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
  let failedAttempts = 0;

  async function tick() {
    if (stopped) return;
    try {
      const response = await fetchImpl(`/api/jobs/${encodeURIComponent(jobId)}`, {
        credentials: "include",
        signal: controller.signal,
      });
      if (!response.ok) throw requestError([408, 429].includes(response.status) || response.status >= 500);
      let job;
      try { job = await response.json(); }
      catch { throw requestError(false); }
      if (!Object.hasOwn(STATUS_LABELS, job?.job_status)) throw requestError(false);
      if (stopped) return;
      failedAttempts = 0;
      options.onUpdate(job);
      if (TERMINAL.has(job.job_status)) return;
      timer = schedule(tick, pollDelay(job.poll_after_ms));
    } catch (error) {
      if (stopped || controller.signal.aborted) return;
      const retryable = error?.retryable !== false;
      if (retryable && failedAttempts < (options.maxRetries ?? AUTO_RETRY_LIMIT)) {
        failedAttempts += 1;
        timer = schedule(tick, retryDelay(failedAttempts));
        return;
      }
      options.onError(POLL_ERROR, { retryable, attempts: failedAttempts + 1 });
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
