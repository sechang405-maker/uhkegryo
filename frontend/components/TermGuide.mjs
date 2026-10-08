import { createElement as h } from "react";

export default function TermGuide({ term }) {
  if (!term) return null;
  return h("article", { className: "term-detail conversation-answer", "aria-label": "용어 안내", "aria-live": "polite" },
    h("span", { className: "term-detail-eyebrow" }, "UH · 용어 안내"),
    h("h3", null, term.label_ko),
    h("div", { className: "answer-prose" }, h("p", null, term.plain_meaning_ko)),
    term.reference_checkpoints?.length > 0 && h("section", { className: "reference-checkpoints" },
      h("h4", null, "레퍼런스에서 볼 부분"),
      h("ul", null, term.reference_checkpoints.map((point, index) => h("li", { key: index }, point)))),
    term.cautions?.length > 0 && h("section", { className: "reference-checkpoints" },
      h("h4", null, "헷갈리기 쉬운 점"),
      h("ul", null, term.cautions.map((point, index) => h("li", { key: index }, point)))),
  );
}
