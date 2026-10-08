"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { countCharacters, createSubmissionController, validateRequestText } from "../lib/agent-submit.mjs";
import { createConversation, listConversations, restoreConversation, resumeConversation, RESTORE_ERROR } from "../lib/server-conversation.mjs";
import { DEMO_JOB, DEMO_REQUEST_TEXT, uiDemoEnabled } from "../lib/demo-job.mjs";
import { HOME_TERMS } from "../lib/home-catalog.mjs";
import { createMindMapSlots, firstSelectableTermId } from "../lib/term-mind-map.mjs";
import { getRecommendedSearchQuery } from "../lib/recommended-query.mjs";
import { searchFixedTerm, searchTermMode } from "../lib/term-search.mjs";
import { createGalleryRows, renderedResultTerms, roleNotice, showThumbnail } from "../lib/result-view.mjs";
import { demoReplyJob, readDemoTurns, saveDemoTurns, stopTurnPolling, upsertTurn, isTurnPending } from "../lib/conversation.mjs";
import ConversationPanel from "../components/ConversationPanel";
import TermGuide from "../components/TermGuide.mjs";
import { ImageSearchLoading, LoadingImage, LoadingIndicator } from "../components/LoadingIndicator.mjs";

const homeSlots = createMindMapSlots(HOME_TERMS);

export default function HomePage() {
  const [requestText, setRequestText] = useState("");
  const [error, setError] = useState("");
  const [submission, setSubmission] = useState(null);
  const [job, setJob] = useState(() => (uiDemoEnabled ? DEMO_JOB : null));
  const [selectedTermId, setSelectedTermId] = useState(null);
  const [pollError, setPollError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [turns, setTurns] = useState(() => uiDemoEnabled
    ? [{ id: "demo-initial", request: DEMO_REQUEST_TEXT, job: DEMO_JOB, demo: true }] : []);
  const [conversationReady, setConversationReady] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const sessionIdRef = useRef(null);
  const sessionLoadRef = useRef(0);
  const [sessions, setSessions] = useState([]);
  const [restoreError, setRestoreError] = useState("");
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [storageFailed, setStorageFailed] = useState(false);
  const chatScrollRef = useRef(null);
  const [activeGalleryRole, setActiveGalleryRole] = useState(null);
  const [failedThumbnails, setFailedThumbnails] = useState({});
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobilePanel, setMobilePanel] = useState("reference");
  const [termGuide, setTermGuide] = useState(null);
  const [termSearch, setTermSearch] = useState(null);
  const termSearchControllerRef = useRef(null);
  const [sketchSearches, setSketchSearches] = useState({});
  const sketchControllersRef = useRef(new Map());
  const [previewPin, setPreviewPin] = useState(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const previewDialogRef = useRef(null);
  const previewTriggerRef = useRef(null);
  const [boardView, setBoardView] = useState("results");
  const menuButtonRef = useRef(null);
  const inputRef = useRef(null);
  const galleryRef = useRef(null);
  const submissionRef = useRef(null);
  const pollerRef = useRef(null);
  const selectedJobRef = useRef(null);
  const mindMapSlots = useMemo(
    () => createMindMapSlots(renderedResultTerms(job, turns)),
    [job, turns],
  );
  const hasTerms = homeSlots.some((slot) => slot.terms.length > 0);
  const activeTermId = homeSlots.some((slot) => slot.terms.some((term) => term.term_id === selectedTermId))
    ? selectedTermId
    : firstSelectableTermId(homeSlots);
  const homeTerm = homeSlots.flatMap((slot) => slot.terms).find((term) => term.term_id === activeTermId) || null;
  const galleryRows = useMemo(() => createGalleryRows(
    boardView === "term-results" && termSearch ? createMindMapSlots([termSearch.term]) : mindMapSlots
  ).map((row) => {
    const replacement = sketchSearches[row.term.term_id]?.term;
    return replacement ? { ...row, term: replacement, pins: replacement.pins.slice(0, 8) } : row;
  }), [mindMapSlots, boardView, termSearch, sketchSearches]);
  const hasGalleryRows = galleryRows.length > 0;
  const galleryTerm = galleryRows.find((row) => row.role === activeGalleryRole)?.term || galleryRows[0]?.term || null;
  const queryTerm = ["results", "term-results"].includes(boardView) && hasGalleryRows ? galleryTerm : homeTerm;
  const recommendedSearchQuery = getRecommendedSearchQuery(queryTerm);
  const pendingTurnIds = turns.filter(isTurnPending).map((turn) => turn.id).join(",");
  const conversationBusy = !conversationReady || isSubmitting || Boolean(pendingTurnIds);
  if (!submissionRef.current) submissionRef.current = createSubmissionController();

  useEffect(() => {
    if (!uiDemoEnabled) return;
    try {
      const restored = readDemoTurns(window.localStorage);
      if (restored) setTurns(restored);
    } catch { setStorageFailed(true); }
    setConversationReady(true);
  }, []);

  useEffect(() => {
    if (uiDemoEnabled) return;
    const controller = new AbortController();
    setRestoreError("");
    setConversationReady(false);
    Promise.all([listConversations({ signal: controller.signal }), restoreConversation({ signal: controller.signal, sessionId: sessionIdRef.current || undefined })]).then(([items, restored]) => {
      if (controller.signal.aborted) return;
      setSessions(items);
      setSessionId(restored.sessionId);
      sessionIdRef.current = restored.sessionId;
      setTurns(restored.turns);
      setJob(restored.turns.at(-1)?.job || null);
      setConversationReady(true);
    }).catch(() => { if (!controller.signal.aborted) setRestoreError(RESTORE_ERROR); });
    return () => controller.abort();
  }, [restoreAttempt]);

  useEffect(() => {
    if (!uiDemoEnabled || !conversationReady) return;
    try { setStorageFailed(!saveDemoTurns(window.localStorage, turns)); }
    catch { setStorageFailed(true); }
  }, [turns, conversationReady]);

  useEffect(() => {
    if (!submission || !job || (job.job_id && job.job_id !== submission.jobId)) return;
    setTurns((entries) => upsertTurn(entries, {
      id: submission.jobId, request: submission.requestText, job, demo: false,
    }));
  }, [submission, job]);

  useEffect(() => {
    if (chatScrollRef.current) chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
  }, [turns, termGuide, mobilePanel]);

  useEffect(() => {
    if (uiDemoEnabled || !conversationReady || !pendingTurnIds) return;
    const latestId = turns.at(-1)?.id;
    const activeSessionId = sessionIdRef.current;
    const poller = resumeConversation(turns, { onUpdate: (turn) => {
      if (sessionIdRef.current !== activeSessionId || activeSessionId !== turn.job?.session_id) return;
      setTurns((entries) => upsertTurn(entries, turn));
      if (turn.id === latestId) setJob(turn.job);
    }, onError: (id, message) => {
      if (sessionIdRef.current !== activeSessionId) return;
      setPollError(message);
      setTurns((entries) => stopTurnPolling(entries, id));
    } });
    pollerRef.current = poller;
    return () => {
      poller.stop();
      if (pollerRef.current === poller) pollerRef.current = null;
    };
  }, [pendingTurnIds, conversationReady]);

  useEffect(() => () => termSearchControllerRef.current?.abort(), []);
  useEffect(() => {
    function closeHelpOutside(event) {
      document.querySelectorAll(".category-search-help[open]").forEach((help) => {
        if (!help.contains(event.target)) help.open = false;
      });
    }
    document.addEventListener("click", closeHelpOutside, true);
    return () => document.removeEventListener("click", closeHelpOutside, true);
  }, []);
  useEffect(() => () => {
    for (const controller of sketchControllersRef.current.values()) controller.abort();
  }, []);

  useEffect(() => {
    if (previewPin && !previewDialogRef.current.open) previewDialogRef.current.showModal();
  }, [previewPin]);

  useEffect(() => {
    if (job !== selectedJobRef.current) {
      selectedJobRef.current = job;
      setSelectedTermId(firstSelectableTermId(mindMapSlots));
      setFailedThumbnails({});
      resetSketchSearches();
    }
  }, [job, mindMapSlots]);

  useEffect(() => {
    setActiveGalleryRole((current) => (
      galleryRows.some((row) => row.role === current) ? current : galleryRows[0]?.role || null
    ));
  }, [galleryRows]);

  useEffect(() => {
    if (!["results", "term-results"].includes(boardView)) return;
    const syncMobileGallery = () => {
      if (window.matchMedia("(max-width: 760px)").matches && galleryRef.current) {
        syncGalleryRole(galleryRef.current);
      }
    };
    window.addEventListener("scroll", syncMobileGallery, { passive: true });
    window.addEventListener("resize", syncMobileGallery);
    syncMobileGallery();
    return () => {
      window.removeEventListener("scroll", syncMobileGallery);
      window.removeEventListener("resize", syncMobileGallery);
    };
  }, [boardView, galleryRows]);

  useEffect(() => {
    if (!menuOpen) return;
    function closeOnEscape(event) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButtonRef.current?.focus();
      }
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  async function handleSubmit(event) {
    event.preventDefault();
    await submit(requestText);
  }

  function fillInput(text) {
    setMobilePanel("conversation");
    setRequestText(text);
    setError("");
    inputRef.current?.focus();
  }

  useEffect(() => {
    if (mobilePanel === "conversation" && requestText) inputRef.current?.focus();
  }, [mobilePanel]);

  function toggleMenu(event) {
    menuButtonRef.current = event.currentTarget;
    setMenuOpen((open) => !open);
    if (!window.matchMedia("(max-width: 760px)").matches) {
      document.querySelector(".history-sidebar-entry")?.focus();
    }
  }

  async function openTermSearch(term) {
    setTermGuide(term);
    resetSketchSearches();
    termSearchControllerRef.current?.abort();
    const controller = new AbortController();
    termSearchControllerRef.current = controller;
    setSelectedTermId(term.term_id);
    setActiveGalleryRole(term.role);
    setFailedThumbnails({});
    setTermSearch({ term: { ...term, pins: [], reason_codes: [] }, loading: true });
    setBoardView("term-results");
    setMobilePanel("conversation");
    try {
      const result = uiDemoEnabled
        ? DEMO_JOB.result.reference_plan.terms.find((entry) => entry.term_id === term.term_id) || term
        : await searchFixedTerm(term, { signal: controller.signal });
      if (!controller.signal.aborted) setTermSearch({ term: result, loading: false });
    } catch (error) {
      if (!controller.signal.aborted) setTermSearch({
        term: { ...term, pins: [], reason_codes: ["PIN_SEARCH_UNAVAILABLE"] },
        loading: false, error: error.message,
      });
    }
  }

  function resetSketchSearches() {
    for (const controller of sketchControllersRef.current.values()) controller.abort();
    sketchControllersRef.current.clear();
    setSketchSearches({});
  }

  async function searchCategory(term, suffix) {
    if (sketchControllersRef.current.has(term.term_id)) return;
    const controller = new AbortController();
    sketchControllersRef.current.set(term.term_id, controller);
    setSketchSearches((current) => ({ ...current, [term.term_id]: { ...current[term.term_id], loading: true, pendingSuffix: suffix, error: null } }));
    try {
      const updatedTerm = await searchTermMode(term, suffix, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setSketchSearches((current) => ({ ...current, [term.term_id]: { term: updatedTerm, suffix } }));
        setFailedThumbnails((current) => Object.fromEntries(Object.entries(current)
          .filter(([key]) => !key.startsWith(`${term.term_id}:`))));
      }
    } catch (error) {
      if (!controller.signal.aborted) setSketchSearches((current) => ({
        ...current, [term.term_id]: { ...current[term.term_id], loading: false, pendingSuffix: null, error: error.message },
      }));
    } finally {
      if (sketchControllersRef.current.get(term.term_id) === controller) sketchControllersRef.current.delete(term.term_id);
    }
  }

  async function submit(text) {
    if (conversationBusy || submissionRef.current.isPending()) return;

    const validationError = validateRequestText(text);
    if (validationError) {
      setError(validationError);
      return;
    }
    termSearchControllerRef.current?.abort();
    resetSketchSearches();
    setMobilePanel("reference");
    setTermGuide(null);

    if (uiDemoEnabled) {
      const demoJob = demoReplyJob(text, turns, DEMO_JOB);
      const id = crypto.randomUUID();
      setTurns((entries) => upsertTurn(entries, { id, request: text, job: demoJob, demo: true }));
      setJob(demoJob);
      setBoardView("results");
      setRequestText("");
      setError("");
      setSelectedTermId(firstSelectableTermId(mindMapSlots));
      return;
    }

    pollerRef.current?.stop();
    setBoardView("results");
    setIsSubmitting(true);
    setError("");
    setPollError("");
    setSubmission(null);
    setJob(null);
    setSelectedTermId(null);
    selectedJobRef.current = null;
    try {
      let activeSession = sessionIdRef.current;
      if (!activeSession) {
        const created = await createConversation();
        activeSession = created.session_id;
        setSessions((items) => [created, ...items.filter((item) => item.session_id !== created.session_id)]);
      }
      setSessionId(activeSession);
      sessionIdRef.current = activeSession;
      const result = await submissionRef.current.submit(text, { sessionId: activeSession });
      if (result.ok) {
        setSessions((items) => {
          const selected = items.find((item) => item.session_id === activeSession);
          return selected ? [selected, ...items.filter((item) => item.session_id !== activeSession)] : items;
        });
        setTurns((entries) => upsertTurn(entries, { id: result.jobId, request: text,
          job: { job_status: "queued", poll_after_ms: result.pollAfterMs }, demo: false }));
        setSubmission({ ...result, requestText: text });
        setRequestText("");
      }
      else {
        setError(result.error);
        setMobilePanel("conversation");
      }
    } catch {
      setError("대화 요청을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      setMobilePanel("conversation");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleGalleryScroll(event) {
    syncGalleryRole(event.currentTarget);
  }

  function syncGalleryRole(gallery) {
    const mobile = window.matchMedia("(max-width: 760px)").matches;
    const bounds = gallery.getBoundingClientRect();
    const headerHeight = gallery.closest(".reference-board").querySelector(".board-header").getBoundingClientRect().height;
    if (mobile && (bounds.top > window.innerHeight || bounds.bottom < headerHeight)) return;
    const galleryTop = mobile ? headerHeight : bounds.top;
    const closestRow = galleryRows.reduce((closest, row) => {
      const element = gallery.querySelector(`[data-gallery-role="${row.role}"]`);
      if (!element) return closest;
      const distance = Math.abs(element.getBoundingClientRect().top - galleryTop);
      return !closest || distance < closest.distance ? { role: row.role, distance } : closest;
    }, null);

    if (closestRow) {
      setActiveGalleryRole((current) => current === closestRow.role ? current : closestRow.role);
    }
  }

  function navigateBoard(view) {
    setTermGuide(null);
    resetSketchSearches();
    termSearchControllerRef.current?.abort();
    setBoardView(view);
    setMobilePanel("reference");
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  }

  async function openSession(session) {
    if (isSubmitting || session.session_id === sessionIdRef.current) return;
    const loadId = ++sessionLoadRef.current;
    setTermGuide(null);
    setMenuOpen(false);
    resetSketchSearches();
    termSearchControllerRef.current?.abort();
    pollerRef.current?.stop();
    setConversationReady(false);
    setRestoreError("");
    setSubmission(null);
    setPollError("");
    setSessionId(session.session_id);
    sessionIdRef.current = session.session_id;
    setSessions((items) => [session, ...items.filter((item) => item.session_id !== session.session_id)]);
    setTurns([]);
    setJob(null);
    try {
      const restored = await restoreConversation({ sessionId: session.session_id });
      if (loadId !== sessionLoadRef.current) return;
      setTurns(restored.turns);
      setJob(restored.turns.at(-1)?.job || null);
      setConversationReady(true);
      setActiveGalleryRole(null);
      setBoardView("results");
      setMobilePanel("reference");
    } catch {
      if (loadId === sessionLoadRef.current) {
        setRestoreError(RESTORE_ERROR);
        setConversationReady(true);
      }
    }
  }

  async function startNewSession() {
    if (isSubmitting) return;
    const loadId = ++sessionLoadRef.current;
    pollerRef.current?.stop();
    setConversationReady(false);
    setRestoreError("");
    try {
      const created = await createConversation();
      if (loadId !== sessionLoadRef.current) return;
      setSessions((items) => [created, ...items.filter((item) => item.session_id !== created.session_id)]);
      setSessionId(created.session_id);
      sessionIdRef.current = created.session_id;
      setTurns([]);
      setJob(null);
      setSubmission(null);
      setPollError("");
      setConversationReady(true);
      setRestoreError("");
      setTermGuide(null);
      setBoardView("results");
      setMobilePanel("reference");
      setMenuOpen(false);
    } catch {
      if (loadId === sessionLoadRef.current) {
        setConversationReady(true);
        setRestoreError("새 세션을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.");
      }
    }
  }

  return (
    <main className="workspace" data-mobile-panel={mobilePanel}>
      <nav className="mobile-workspace-nav" aria-label="작업 화면">
        <button type="button" aria-label="UH케그려 홈" onClick={() => navigateBoard("home")}>UH</button>
        <button type="button" aria-pressed={mobilePanel === "reference"} aria-controls="reference-panel"
          onClick={() => setMobilePanel("reference")}>레퍼런스</button>
        <button type="button" aria-pressed={mobilePanel === "conversation"} aria-controls="conversation-panel"
          onClick={() => setMobilePanel("conversation")}>대화</button>
        <button type="button" aria-expanded={menuOpen} aria-controls="history-sidebar" onClick={toggleMenu}>세션</button>
      </nav>
      <aside id="history-sidebar" className="history-sidebar" data-open={menuOpen} aria-label="세션 목록">
        <button className="brand-identity brand-home-button" type="button" aria-label="UH케그려 홈"
          onClick={() => navigateBoard("home")}>
          <span className="brand-mark" aria-hidden="true">UH</span>
          <span className="brand-name">UH케그려</span>
        </button>
        <nav className="history-sidebar-list" aria-label="세션 목록">
          <button className="history-sidebar-entry" type="button" disabled={!conversationReady || isSubmitting} onClick={startNewSession}>새 세션</button>
          {uiDemoEnabled ? <button className="history-sidebar-entry" type="button" aria-current="page">미리보기 대화</button>
            : sessions.map((session) => (
              <button className="history-sidebar-entry" type="button" key={session.session_id}
                disabled={isSubmitting} title={new Date(session.created_at).toLocaleString("ko-KR")}
                aria-current={sessionId === session.session_id ? "page" : undefined}
                onClick={() => openSession(session)}>
                <span className="history-sidebar-title">{new Date(session.created_at).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" })}</span>
              </button>
            ))}
          {!uiDemoEnabled && !sessions.length && <p className="history-sidebar-empty">아직 대화 세션이 없습니다.</p>}
        </nav>
      </aside>
      {menuOpen && <button className="history-sidebar-dismiss" type="button" aria-label="세션 목록 닫기"
        onClick={() => { setMenuOpen(false); menuButtonRef.current?.focus(); }} />}
      <section id="reference-panel" className="reference-board" aria-label="레퍼런스">
        <header className="board-header">
          <button className="brand-identity brand-mobile-home" type="button" aria-label="UH케그려 홈"
            onClick={() => navigateBoard("home")}>
            <span className="brand-mark" aria-hidden="true">UH</span><span className="brand-name">UH케그려</span>
          </button>
          <button className="history-sidebar-toggle" type="button" aria-expanded={menuOpen}
            aria-controls="history-sidebar" onClick={toggleMenu}>세션</button>
          {recommendedSearchQuery && (
            <div className="recommended-query" aria-label="즉시 검색">
              <div className="query-value">
                <code tabIndex={0} aria-label="추천 검색어" aria-describedby="full-query-tooltip">{recommendedSearchQuery}</code>
                <span id="full-query-tooltip" className="full-query-tooltip" role="tooltip">{recommendedSearchQuery}</span>
              </div>
              <a href={`https://kr.pinterest.com/search/pins/?${new URLSearchParams({ q: recommendedSearchQuery })}`}
                aria-label="Pinterest에서 검색" aria-describedby="instant-search-tooltip"
                target="_blank" rel="noopener noreferrer">
                Pinterest ↗
                <span id="instant-search-tooltip" className="instant-search-tooltip" role="tooltip">
                  Pinterest 검색 결과는 계정, 이용 기록 등에 따라 달라질 수 있습니다.
                </span>
              </a>
            </div>
          )}
        </header>
        {boardView === "results" && conversationBusy && conversationReady ? (
          <div className="board-search-loading"><ImageSearchLoading label="요청을 처리하는 중입니다…" /></div>
        ) : ["results", "term-results"].includes(boardView) && hasGalleryRows ? (
          <div className="pin-gallery" ref={galleryRef} data-single={galleryRows.length === 1}
            aria-label="카테고리별 Pinterest 핀 썸네일" onScroll={handleGalleryScroll}>
            <button className="gallery-back-button" type="button" onClick={() => navigateBoard("home")}>← 용어 둘러보기</button>
            {galleryRows.map(({ role, roleLabel, term, pins }) => (
              <section className="pin-gallery-row" data-gallery-role={role} key={role} aria-label={`${roleLabel} 검색 결과`}>
                <div className="pin-gallery-toolbar">
                <button className="pin-gallery-heading" type="button"
                  aria-pressed={term.term_id === galleryTerm?.term_id}
                  aria-label={`${roleLabel} ${term.label_ko} 검색어 보기`}
                  onClick={() => { setSelectedTermId(term.term_id); setActiveGalleryRole(role); }}>
                  <span>{roleLabel}</span>
                  <strong>{term.label_ko}</strong>
                  {term.term_id === galleryTerm?.term_id && <span className="active-term-badge">보고 있는 용어</span>}
                </button>
                  <div className="category-search-controls">
                  <div className="category-search-actions" role="group" aria-label={`${roleLabel} 검색 모드`}>
                    {[{ suffix: "drawing", label: "일반" }, { suffix: "sketch", label: "스케치" },
                      { suffix: "mannequinization", label: "도형화" }].map((mode) => (
                      <button className="sketch-search-button" type="button" key={mode.suffix}
                        aria-pressed={(sketchSearches[term.term_id]?.suffix || "drawing") === mode.suffix}
                        aria-busy={Boolean(sketchSearches[term.term_id]?.loading && sketchSearches[term.term_id]?.pendingSuffix === mode.suffix)}
                        disabled={sketchSearches[term.term_id]?.loading ||
                          (boardView === "term-results" && termSearch?.loading)}
                        aria-label={`${roleLabel} ${term.label_ko} ${mode.label} 검색`}
                        onClick={() => searchCategory(term, mode.suffix)}>
                        {mode.label}
                      </button>
                    ))}
                  </div>
                  <details className="category-search-help">
                    <summary aria-label="도형화란?">?</summary>
                    <p><strong>도형화란?</strong>몸을 상자·원통·구로 나눈 구조 참고 자료입니다.</p>
                  </details>
                  </div>
                </div>
                {sketchSearches[term.term_id]?.loading && <LoadingIndicator size="small" label={`${({ drawing: "일반", sketch: "스케치", mannequinization: "도형화" })[sketchSearches[term.term_id]?.pendingSuffix]} 레퍼런스를 찾는 중입니다…`} />}
                {sketchSearches[term.term_id]?.error && <p className="sketch-search-notice" role="alert">{sketchSearches[term.term_id].error}</p>}
                <div className="pin-gallery-items">
                  {boardView === "term-results" && termSearch?.loading && <ImageSearchLoading />}
                  {boardView === "term-results" && termSearch?.error && <p className="pin-unavailable" role="alert">{termSearch.error}</p>}
                  {roleNotice(term) && <p className="pin-unavailable" role="status">{roleNotice(term)}</p>}
                  {boardView === "term-results" && !termSearch?.loading && (termSearch?.error || roleNotice(term)) &&
                    <button type="button" onClick={() => openTermSearch(term)}>다시 찾기</button>}
                  {!pins.length && !roleNotice(term) && !(boardView === "term-results" && termSearch?.loading) && <p className="pin-unavailable">표시할 핀이 없습니다.</p>}
                  {pins.map((pin, index) => showThumbnail(pin) && !failedThumbnails[`${term.term_id}:${pin.pin_id}`] ? (
                    <button
                      className="pin-gallery-card"
                      type="button"
                      key={pin.pin_id}
                      aria-label={`${roleLabel} ${term.label_ko} 핀 ${index + 1} 확대 보기`}
                      onClick={(event) => {
                        previewTriggerRef.current = event.currentTarget;
                        setPreviewFailed(false);
                        setPreviewPin({ ...pin, label: `${roleLabel} · ${term.label_ko}` });
                      }}
                    >
                      <LoadingImage
                        key={pin.thumbnail_url}
                        src={pin.thumbnail_url}
                        alt={`${term.label_ko} 레퍼런스 ${index + 1}`}
                        loading="lazy"
                        referrerPolicy="no-referrer"
                        onError={() => setFailedThumbnails((current) => ({ ...current, [`${term.term_id}:${pin.pin_id}`]: true }))}
                      />
                    </button>
                  ) : <div className="pin-gallery-card pin-unavailable" key={pin.pin_id}>접근할 수 없는 Pin</div>)}
                </div>
              </section>
            ))}
          </div>
        ) : hasTerms ? (
          <div className="mind-map-stage" aria-label="예시 용어 관계도">
            <p className="mind-map-guide">검수된 예시 용어 · 용어를 누르면 레퍼런스를 검색해요.</p>
            <div className="mind-map">
              <svg className="mind-map-connectors" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <line x1="50" y1="61.2" x2="50" y2="29" />
                <line x1="50" y1="61.2" x2="69.1" y2="37.8" />
                <line x1="50" y1="61.2" x2="88.5" y2="61.2" />
                <line x1="50" y1="61.2" x2="11.5" y2="61.2" />
                <line x1="50" y1="61.2" x2="30.9" y2="37.8" />
              </svg>
              <button className="mind-map-hub" type="button" aria-label="중앙 브랜드 홈"
                aria-describedby="hub-menu-tip" onClick={() => navigateBoard("home")}>
                <span aria-hidden="true">UH</span>
                <span id="hub-menu-tip" className="hub-menu-tip" role="tooltip">홈으로 이동</span>
              </button>
              {homeSlots.map((slot, index) => (
                <section className={`mind-map-group mind-map-group-${index}`} key={slot.role} aria-label={`${slot.roleLabel} TERM_CARD`}>
                  <span className="mind-map-group-role">{slot.roleLabel}</span>
                  <div className="mind-map-group-cards">
                    {slot.terms.length > 0 ? slot.terms.map((term) => (
                      <button
                        type="button"
                        className="mind-map-node"
                        aria-label={`${slot.roleLabel} ${term.label_ko}`}
                        aria-pressed={term.term_id === activeTermId}
                        key={term.term_id}
                        onClick={() => openTermSearch(term)}
                      >
                        {term.label_ko}
                      </button>
                    )) : (
                      <div className="mind-map-node mind-map-node-empty">해석 없음</div>
                    )}
                  </div>
                </section>
              ))}
            </div>
          </div>
        ) : (
          <div className="board-empty">
            <span className="board-empty-icon" aria-hidden="true">🖌️</span>
            <h1 id="reference-title">그림의 출발점을 찾아보세요</h1>
            <p>오른쪽에 그리고 싶은 캐릭터를 설명하면 레퍼런스 탐색을 시작합니다.</p>
          </div>
        )}
      </section>

      <aside id="conversation-panel" className="prompt-panel" aria-labelledby="prompt-title">
        <div className="panel-top" ref={chatScrollRef}>
          {uiDemoEnabled && <span className="demo-badge">대화 UI 더미 · LLM 미연결</span>}
          <h2 id="prompt-title">UH케 그릴 건가요?</h2>
          <p className="conversation-notice">{uiDemoEnabled
            ? "더미 대화만 이 브라우저에 저장됩니다. 개인·민감 정보는 입력하지 마세요."
            : "같은 브라우저의 쿠키로 최근 대화를 복원합니다. 쿠키 삭제·대화 만료 후에는 복원되지 않습니다."}</p>
          {restoreError && <div role="alert"><p>{restoreError}</p>
            <button type="button" onClick={() => setRestoreAttempt((value) => value + 1)}>대화 다시 불러오기</button></div>}
          {storageFailed && <p className="form-error" role="status">브라우저 저장을 사용할 수 없어 새로고침 후 더미 대화가 유지되지 않습니다.</p>}
          <ConversationPanel key={sessionId || "no-session"} turns={turns} onChoice={fillInput} onRetry={fillInput} retryDisabled={conversationBusy} />
          <TermGuide term={termGuide} />
          {((!conversationReady && !restoreError) || isSubmitting) && <div className="receipt"><LoadingIndicator
            label={!conversationReady ? "대화를 불러오는 중…" : "요청을 보내는 중…"} /></div>}
          {pollError && <p className="form-error" role="alert">{pollError}</p>}
        </div>

        <form className="composer" onSubmit={handleSubmit} noValidate>
          <div className="composer-input-frame" data-invalid={Boolean(error)}>
          <textarea
            id="request-text"
            ref={inputRef}
            name="request_text"
            aria-label="캐릭터 설명"
            rows={5}
            value={requestText}
            disabled={conversationBusy}
            onChange={(event) => {
              setRequestText(event.target.value);
              if (error) setError("");
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="원하는 체형, 포즈, 시점을 적어 주세요"
            aria-invalid={Boolean(error)}
            aria-describedby={`request-hint request-count${error ? " request-error" : ""}`}
          />
          </div>
          {error && <p id="request-error" className="form-error" role="alert">{error}</p>}
          <div className="composer-footer">
            <span id="request-hint" className="input-hint">Enter로 검색 · Shift+Enter로 줄바꿈</span>
            <span id="request-count" className="character-count">{countCharacters(requestText)} / 500</span>
          </div>
        </form>
      </aside>
      <dialog className="image-preview" ref={previewDialogRef} aria-labelledby="preview-title"
        onClick={(event) => { if (event.target === event.currentTarget) event.currentTarget.close(); }}
        onClose={() => { setPreviewPin(null); previewTriggerRef.current?.focus(); }}>
        {previewPin && <div className="image-preview-content">
          <header className="image-preview-header">
            <h2 id="preview-title">{previewPin.label}</h2>
            <button type="button" autoFocus onClick={() => previewDialogRef.current.close()}>닫기</button>
          </header>
          {previewFailed ? <p role="status">이미지를 표시할 수 없습니다. 핀 원본에서 확인해 주세요.</p>
            : <LoadingImage key={previewPin.thumbnail_url} size="medium" src={previewPin.thumbnail_url} alt={`${previewPin.label} 확대 레퍼런스`}
                referrerPolicy="no-referrer" onError={() => setPreviewFailed(true)} />}
          <footer><span>썸네일 확대 보기 · 원본 해상도는 핀에서 확인하세요.</span>
            <a href={previewPin.pin_url} target="_blank" rel="noopener noreferrer">핀 원본 열기 ↗</a>
          </footer>
        </div>}
      </dialog>
    </main>
  );
}
