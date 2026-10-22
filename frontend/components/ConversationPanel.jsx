import { isTurnPending } from "../lib/conversation.mjs";
import { STATUS_LABELS } from "../lib/job-polling.mjs";
import { LoadingIndicator } from "./LoadingIndicator.mjs";
import MarkdownAnswer from "./MarkdownAnswer.mjs";

export default function ConversationPanel({ turns, reopenableTurnIds = new Set(), onOpenReferences,
  onRetryStatus, retryStatusBusy = false }) {
  return <div className="conversation-thread" role="log" aria-label="캐릭터 설명 대화" aria-live="polite" aria-relevant="additions text">
    {turns.map((turn) => <div className="conversation-turn" key={turn.id}>
      <article className="chat-request" aria-label="사용자 요청">
        <span>내 요청</span><p>{turn.request}</p>
      </article>
      {turn.polling_stopped ? <div className="receipt polling-recovery">
        <p role="alert">{turn.polling_error || "상태 확인이 중단되었습니다."}</p>
        <button className="polling-retry-button" type="button" disabled={retryStatusBusy}
          onClick={() => onRetryStatus(turn.id)}>상태 다시 확인</button>
      </div>
        : isTurnPending(turn) ? <div className="receipt">
        <LoadingIndicator label={STATUS_LABELS[turn.job?.job_status] || "답변 대기 중…"} />
      </div>
        : <article className="term-detail conversation-answer" aria-label="통합 답변">
          <span className="term-detail-eyebrow">{turn.demo ? "UH · 더미 답변" : "UH · 답변"}</span>
          <MarkdownAnswer job={turn.job} />
          {reopenableTurnIds.has(turn.id) && <button className="conversation-reference-button" type="button"
            onClick={() => onOpenReferences(turn)}>이 답변의 레퍼런스 보기</button>}
        </article>}
    </div>)}
  </div>;
}

