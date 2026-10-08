const DEMO_STORAGE_KEY = "uh-studio-demo-conversation-v1";
const TERMINAL = new Set(["completed", "failed"]);

export function upsertTurn(turns, turn) {
  const index = turns.findIndex((entry) => entry.id === turn.id);
  return index < 0 ? [...turns, turn] : turns.map((entry, position) => position === index
    ? { ...entry, ...turn, polling_stopped: !TERMINAL.has(turn.job?.job_status)
      && Boolean(entry.polling_stopped || turn.polling_stopped) } : entry);
}

export function stopTurnPolling(turns, turnId) {
  return turns.map((turn) => turn.id === turnId && isTurnPending(turn)
    ? { ...turn, polling_stopped: true } : turn);
}

export function answerForJob(job) {
  if (job?.job_status === "failed") return job.failure?.user_message || "요청을 완료하지 못했습니다. 다시 시도해 주세요.";
  if (job?.job_status !== "completed") return "";
  const result = job.result || {};
  if (result.agent_status === "needs_clarification") return result.clarifying_question || "원하는 조건을 조금 더 알려주세요.";
  if (["unsafe_input", "out_of_scope"].includes(result.agent_status)) return result.user_message || "캐릭터의 체형·포즈·시점을 설명해 주세요.";
  if (result.agent_status === "memory_answer") return result.memory_answer || result.user_message || "대화 기록의 답변을 확인할 수 없습니다.";
  return result.answer_text?.trim() || result.user_message?.trim() || "통합 답변은 백엔드 연결 후 표시됩니다. 현재 응답에는 통합 답변이 없습니다.";
}

export function isTurnPending(turn) {
  return !turn.polling_stopped && !TERMINAL.has(turn.job?.job_status);
}

export function demoReplyJob(request, turns, template) {
  const previous = turns.at(-1)?.request;
  const body = previous
    ? `앞선 요청은 “${previous}”였고, 이번 요청은 “${request}”입니다.\n\n실제 연결 후에는 이전 조건을 참고해 변경한 부분을 설명하는 통합 답변이 이곳에 이어집니다.`
    : template.result.answer_text;
  return { ...template, result: { ...template.result, answer_text: `${body}\n\n※ 대화 흐름 확인용 더미입니다. 실제 LLM 해석이나 새로운 이미지 검색은 실행하지 않았습니다.` } };
}

export function readDemoTurns(storage) {
  try {
    const raw = storage.getItem(DEMO_STORAGE_KEY);
    if (!raw) return null;
    const turns = JSON.parse(raw);
    if (!Array.isArray(turns) || turns.length > 50 || turns.some((turn) =>
      turn?.demo !== true || typeof turn.id !== "string" || !turn.id ||
      typeof turn.request !== "string" || turn.request.length > 1000 ||
      turn.job?.job_status !== "completed" || typeof turn.job.result?.answer_text !== "string" ||
      turn.job.result.answer_text.length > 8000)) return null;
    return turns.map((turn) => ({ id: turn.id, request: turn.request, demo: true,
      job: { job_status: "completed", result: { agent_status: "success", answer_text: turn.job.result.answer_text } } }));
  } catch { return null; }
}

export function saveDemoTurns(storage, turns) {
  try {
    const safeTurns = turns.filter((turn) => turn.demo && turn.job?.job_status === "completed").slice(-50)
      .map((turn) => ({ id: turn.id, request: turn.request, demo: true,
        job: { job_status: "completed", result: { agent_status: "success", answer_text: answerForJob(turn.job) } } }));
    storage.setItem(DEMO_STORAGE_KEY, JSON.stringify(safeTurns));
    return true;
  } catch { return false; }
}
