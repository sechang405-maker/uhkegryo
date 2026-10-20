import { resultTerms } from "./result-view.mjs";
import { createHistoryLoader } from "./server-conversation.mjs";

// Gallery selection is independent of the live conversation/polling state.
export function createGallerySelection(options) {
  let session = null;
  let selected = null;
  const loader = createHistoryLoader(options);
  return {
    reset(sessionId) {
      session = sessionId;
      selected = null;
      loader.cancel();
      options.onSelection(null);
      options.onJob(null);
    },
    begin(sessionId) {
      loader.cancel();
      session = sessionId;
      selected = null;
      options.onSelection(null);
    },
    async open(entry) {
      if (entry.job?.job_status !== "completed" || (!entry.demo && entry.job.session_id !== session)) return;
      selected = entry.id;
      options.onSelection(selected);
      options.onJob(null);
      await loader.open(entry);
    },
    live(job, sessionId) {
      const failedRecommendation = job?.result?.recommendation_adoption && job.result.agent_status === "partial_result";
      if (sessionId === session && selected === null && resultTerms(job).length && !failedRecommendation) options.onJob(job);
    },
    restore(job, selectionId, sessionId) {
      loader.cancel();
      session = sessionId;
      selected = selectionId;
      options.onSelection(selected);
      options.onJob(job);
    },
    dispose() { loader.cancel(); },
  };
}
