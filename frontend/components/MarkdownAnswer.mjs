import { createElement as h } from "react";
import Markdown from "react-markdown";
import { answerForJob } from "../lib/conversation.mjs";
import { resultTerms } from "../lib/result-view.mjs";

const allowedElements = ["p", "strong", "em", "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "h4", "br"];
const components = {
  h1: ({ children }) => h("h3", null, children),
  h2: ({ children }) => h("h3", null, children),
};

export default function MarkdownAnswer({ text, job }) {
  if (job) {
    const terms = resultTerms(job).filter(term => typeof term.label_ko === "string" && term.label_ko.trim()
      && typeof term.plain_meaning_ko === "string" && term.plain_meaning_ko.trim());
    if (!terms.length) return h(MarkdownAnswer, { text: answerForJob(job) });
    const summary = job.result.answer_text?.trim() || job.result.user_message?.trim();
    return h("div", { className: "answer-sections" },
      ...terms.map(term => h("section", { className: "answer-card-section", key: term.term_id },
        // The API pairs these catalog fields by term_id; never split model prose to guess ownership.
        // A semantic h2 is the rendered equivalent of ##, with the label escaped as plain text.
        h("h2", { className: "answer-card-title" }, term.label_ko),
        h(MarkdownAnswer, { text: term.plain_meaning_ko }),
        term.selection_reason && term.selection_reason !== term.plain_meaning_ko
          ? h("div", { className: "answer-card-reason" }, h(MarkdownAnswer, { text: term.selection_reason })) : null,
      )),
      summary ? h("section", { className: "answer-summary" },
        h("h3", null, "종합 설명"), h(MarkdownAnswer, { text: summary })) : null,
    );
  }
  return h("div", { className: "answer-prose answer-markdown" },
    h(Markdown, { allowedElements, components, skipHtml: true, unwrapDisallowed: true }, text));
}

