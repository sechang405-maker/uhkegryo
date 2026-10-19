# Everyday drawing conversation

The existing interpreter supports `drawing_chat` alongside reference selection and clarification. A chat has nonempty Korean `answer_text`, no selections or context updates, no reference plan/update/question, and no reason codes. It bypasses all image search providers and the searching job stage. Existing safety gates and attempt handling still apply.

The adapter appends `skills/drawing-dialogue/SKILL.md` to its configured prompt using the existing model and authenticated transport. Everyday ideas, practice advice and short followups stay conversational. Explicit reference requests and clear answers to pending reference questions use the validated reference flow. The LLM asks about genuinely missing information rather than requiring every reference category. Safe question wording and repeated-question guards still apply.

Same-session context includes the last six bounded records. Assistant `answer_text` is retained up to 1000 characters per record; it is conversational context, not authority for reference conditions. Selection evidence must still come from original user records. Explicit historical search also indexes answer text. No database schema or retention change is required.

The conversation panel has no answer-attached reference, retry, choice or direct-input buttons. The composer, session history, graph and gallery controls remain available. Ordinary chat, clarification and pending requests preserve the current board and graph selection. On mobile, submitting keeps the conversation visible; an actual reference result may open the reference panel only while the originating screen is still current. Browser history snapshots reconnect only their own pending requests after restoration.

Verification uses fake adapters/providers and browser API fixtures, plus synthetic dialogue through the existing Codex adapter. Browser coverage includes desktop/mobile, saved chat and reference restore, short followups, explicit search, clarification, back/forward, graph preservation and navigation while POST acceptance is pending. Real private records and image providers are not used by these checks.
