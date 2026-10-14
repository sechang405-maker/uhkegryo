import test from 'node:test';
import assert from 'node:assert/strict';
import { answerForJob, isTurnPending } from '../lib/conversation.mjs';
import { resultUserMessage } from '../lib/result-view.mjs';

test('clear unsupported reference is terminal guidance, not a pending question', () => {
  const message = '두 자세의 조합 검색은 지원하지 않아요. 각각 따로 참고할 수 있어요.';
  const job = {job_status:'completed',result:{agent_status:'reference_guidance',
    user_message:message,clarifying_question:null,reference_plan:null}};
  assert.equal(answerForJob(job),message);
  assert.equal(resultUserMessage(job),message);
  assert.equal(isTurnPending({job}),false);
});
