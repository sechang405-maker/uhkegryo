import { answerForJob, isTurnPending } from "../lib/conversation.mjs";
import { STATUS_LABELS } from "../lib/job-polling.mjs";
import { clarificationChoices } from "../lib/result-view.mjs";
import { LoadingIndicator } from "./LoadingIndicator.mjs";
import MarkdownAnswer from "./MarkdownAnswer.mjs";

export default function ConversationPanel({ turns, onChoice, onRetry, retryDisabled }) {
  return <div className="conversation-thread" role="log" aria-label="캐릭터 설명 대화" aria-live="polite" aria-relevant="additions text">
    {turns.map((turn) => <div className="conversation-turn" key={turn.id}>
      <article className="chat-request" aria-label="사용자 요청">
        <span>내 요청</span><p>{turn.request}</p>
      </article>
      {turn.polling_stopped ? <div className="receipt"><p role="status">상태 확인이 중단되었습니다.</p></div>
        : isTurnPending(turn) ? <div className="receipt">
        <LoadingIndicator label={STATUS_LABELS[turn.job?.job_status] || "답변 대기 중…"} />
      </div>
        : <article className="term-detail conversation-answer" aria-label="통합 답변">
          <span className="term-detail-eyebrow">{turn.demo ? "UH · 더미 답변" : "UH · 답변"}</span>
          <MarkdownAnswer text={answerForJob(turn.job)} />
          {turn.job?.job_status === "failed" && onRetry && <div className="result-actions">
            <button type="button" disabled={retryDisabled} onClick={() => onRetry(turn.request)}
              title="원래 요청을 입력란에 복원합니다. 확인 후 Enter로 전송하세요.">재시도</button>
          </div>}
          {turn.job?.result?.agent_status === "needs_clarification" && <div className="result-actions">
            {clarificationChoices(turn.job.result).map((choice) =>
              <button type="button" key={choice.label} onClick={() => onChoice(choice.request_text)}>{choice.label}</button>)}
            <button type="button" onClick={() => onChoice("")}>직접 입력하기</button>
          </div>}
        </article>}
    </div>)}
  </div>;
}
