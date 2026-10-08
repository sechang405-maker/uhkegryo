import { createElement as h } from "react";
import Markdown from "react-markdown";

const allowedElements = ["p", "strong", "em", "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "h4", "br"];
const components = {
  h1: ({ children }) => h("h3", null, children),
  h2: ({ children }) => h("h3", null, children),
};

export default function MarkdownAnswer({ text }) {
  return h("div", { className: "answer-prose answer-markdown" },
    h(Markdown, { allowedElements, components, skipHtml: true, unwrapDisallowed: true }, text));
}
