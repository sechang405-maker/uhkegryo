"use client";

import { useEffect, useMemo, useState } from "react";
import { createPersonalTermClient, editablePersonalTerm, newPersonalTermRequestId } from "../lib/personal-terms.mjs";
import { graphCategoryColor } from "../lib/term-graph-colors.mjs";

const ROLE_LABELS = { body: "체형", pose: "포즈", composition: "구도", perspective: "투시" };
const arrayText = (values) => Array.isArray(values) ? values.join("\n") : (values || "");
const textArray = (value) => (Array.isArray(value) ? value : value.split("\n")).map((item) => item.trim()).filter(Boolean);

export default function PersonalTermCreator({ open, onClose, onItemsChange }) {
  const client = useMemo(() => createPersonalTermClient(), []);
  const [sourceInput, setSourceInput] = useState("");
  const [draft, setDraft] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [requestId, setRequestId] = useState(null);

  async function refresh() {
    try { const next=(await client.list()).items || [];setItems(next);onItemsChange?.(next); } catch (cause) { setError(cause.message); }
  }
  useEffect(() => { if (open) refresh(); }, [open]);
  if (!open) return null;

  async function generate(event, retryFailed = false) {
    event?.preventDefault();
    const key = requestId || newPersonalTermRequestId();
    setRequestId(key); setBusy(true); setError("");
    try {
      const result = await client.generate(sourceInput, key, retryFailed);
      setDraft(editablePersonalTerm(result.term));
      setDraft((current) => ({ ...current, term_id: result.term.term_id, status: result.term.status }));
      setWarnings(result.duplicate_warnings || []);
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  function field(name, value) { setDraft((current) => ({ ...current, [name]: value })); }
  async function save() {
    setBusy(true); setError("");
    try {
      const payload = {
        ...draft,
        reference_checkpoints_ko: textArray(draft.reference_checkpoints_ko),
        cautions_ko: textArray(draft.cautions_ko), aliases_ko: textArray(draft.aliases_ko),
        query_fragments_en: textArray(draft.query_fragments_en),
      };
      delete payload.term_id; delete payload.status;
      await client.update(draft.term_id, payload);
      const saved = await client.confirm(draft.term_id);
      setDraft(null); setWarnings([]); setSourceInput(""); setRequestId(null);
      setItems((current) => { const next=[saved,...current.filter((item)=>item.term_id!==saved.term_id)];onItemsChange?.(next);return next; });
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  return <div className="personal-term-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="personal-term-dialog" role="dialog" aria-modal="true" aria-labelledby="personal-term-title">
      <header><div><span>나만의 AI 초안</span><h2 id="personal-term-title">새 용어 만들기</h2></div>
        <button type="button" aria-label="닫기" onClick={onClose}>×</button></header>
      <p className="personal-term-scope">저장한 개인 용어는 해당 카테고리의 3D 그래프에 표시됩니다. 개인 용어 검색 연결은 다음 단계에서 제공됩니다.</p>
      {!draft ? <form onSubmit={generate}>
        <label htmlFor="personal-term-input">원하는 자세나 그림 개념 설명</label>
        <textarea id="personal-term-input" value={sourceInput} maxLength={300} required
          placeholder="예: 발레에서 한쪽 다리를 뒤로 길게 뻗는 우아한 자세"
          onChange={(event) => { setSourceInput(event.target.value); setRequestId(null); }} />
        <button className="personal-term-primary" disabled={busy || !sourceInput.trim()}>{busy ? "AI 초안 만드는 중…" : "AI 초안 만들기"}</button>
      </form> : <div className="personal-term-review">
        <p><strong>AI가 만든 초안입니다.</strong> 저장 전 내용을 직접 확인하고 수정해 주세요.</p>
        {warnings.length > 0 && <div className="personal-term-warning" role="alert"><strong>비슷한 용어가 있습니다.</strong>
          <ul>{warnings.map((warning) => <li key={`${warning.source}:${warning.term_id}`}>{warning.label_ko} ({warning.match_kind === "exact" ? "동일" : "유사"})</li>)}</ul>
          자동으로 합치거나 대체하지 않습니다.</div>}
        <div className="personal-term-grid">
          <label>카테고리<select value={draft.role} onChange={(event) => field("role", event.target.value)}>{Object.entries(ROLE_LABELS).map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label>한국어 이름<input value={draft.label_ko} onChange={(event) => field("label_ko", event.target.value)} /></label>
          <label>영어 이름<input value={draft.label_en} onChange={(event) => field("label_en", event.target.value)} /></label>
        </div>
        <label>용어 설명<textarea value={draft.plain_meaning_ko} onChange={(event) => field("plain_meaning_ko", event.target.value)} /></label>
        <label>확인 포인트 (한 줄에 하나)<textarea value={arrayText(draft.reference_checkpoints_ko)} onChange={(event) => field("reference_checkpoints_ko", event.target.value)} /></label>
        <label>한국어 별칭 (한 줄에 하나)<textarea value={arrayText(draft.aliases_ko)} onChange={(event) => field("aliases_ko", event.target.value)} /></label>
        <label>검색용 영어 표현 (한 줄에 하나)<textarea value={arrayText(draft.query_fragments_en)} onChange={(event) => field("query_fragments_en", event.target.value)} /></label>
        {draft.uncertainty_ko && <p className="personal-term-warning">불확실성: {draft.uncertainty_ko}</p>}
        <div className="personal-term-actions"><button type="button" onClick={() => { setDraft(null); setWarnings([]); setRequestId(null); }}>다시 입력</button>
          <button className="personal-term-primary" type="button" disabled={busy} onClick={save}>{busy ? "저장 중…" : "수정 내용 확인 후 저장"}</button></div>
      </div>}
      {error && <div className="personal-term-error" role="alert"><p>{error}</p>
        {requestId && !draft && <button type="button" disabled={busy} onClick={(event) => generate(event, true)}>같은 요청 다시 시도</button>}</div>}
      <section className="personal-term-list" aria-labelledby="saved-personal-terms"><h3 id="saved-personal-terms">저장한 개인 용어</h3>
        {!items.length ? <p>아직 저장한 개인 용어가 없습니다.</p> : <ul>{items.map((item) => <li key={item.term_id}>
          <span style={{ "--category-color": graphCategoryColor(item.role) }}>{ROLE_LABELS[item.role]}</span>
          <div><strong>{item.label_ko}</strong><p>{item.plain_meaning_ko}</p></div>
          <small>{item.status === "active" ? "저장됨" : "검토 중"}</small>
        </li>)}</ul>}
      </section>
    </section>
  </div>;
}
