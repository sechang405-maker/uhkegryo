"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { countCharacters, createSubmissionController, validateRequestText, shouldSubmitOnEnter } from "../lib/agent-submit.mjs";
import { resizeComposerInput, createScrollEndAnchor } from "../lib/composer-autosize.mjs";
import { createGallerySelection } from "../lib/gallery-selection.mjs";
import { createConversation, listConversations, listConversationPage, mergeSessions, loadOlderConversation, restoreConversation, resumeConversation, RESTORE_ERROR, ensureLocalProfile, deleteConversation, DELETE_CONFIRM } from "../lib/server-conversation.mjs";
import { DEMO_JOB, DEMO_REQUEST_TEXT, uiDemoEnabled } from "../lib/demo-job.mjs";
import { DEMO_SCENARIOS, DEMO_NOTICE, DEMO_INPUT_ERROR, demoTerm } from "../lib/portfolio-demo-fixtures.mjs";
import { createDemoSessionStore } from "../lib/portfolio-demo-sessions.mjs";
import { sessionTitle } from "../lib/session-title.mjs";
import { HOME_TERMS } from "../lib/home-catalog.mjs";
import { createMindMapSlots, firstSelectableTermId } from "../lib/term-mind-map.mjs";
import { getRecommendedSearchQuery, combineRecommendedSearchQueries } from "../lib/recommended-query.mjs";
import { searchFixedTerm, searchTermMode, applySketchResult, applyPreviewRecovery } from "../lib/term-search.mjs";
import { createGalleryRows, renderedResultTerms, resultTerms, roleNotice, showThumbnail, pinUnavailableMessage } from "../lib/result-view.mjs";
import { usableGalleryPins } from "../lib/gallery-pins.mjs";
import { createRecoveryBudget, claimRecovery, finishRecovery } from "../lib/recovery-budget.mjs";
import { stopTurnPolling, upsertTurn, mergeHistoryTurns, isTurnPending } from "../lib/conversation.mjs";
import ConversationPanel from "../components/ConversationPanel";
import TermGuide from "../components/TermGuide.mjs";
import TermGraph from "../components/TermGraph";
import MasonryGallery from "../components/MasonryGallery";
import HistoryDrawer, { HistoryLogo } from "../components/HistoryDrawer";
import { toggleTerm, appendTerms } from "../lib/term-graph.mjs";
import { createScreenHistory } from "../lib/screen-history.mjs";
import { ImageSearchLoading, LoadingImage, LoadingIndicator } from "../components/LoadingIndicator.mjs";

const homeSlots = createMindMapSlots(HOME_TERMS);

export default function HomePage() {
  const [requestText, setRequestText] = useState("");
  const [graphTermIds, setGraphTermIds] = useState([]);
  const [graphFocusId, setGraphFocusId] = useState(HOME_TERMS[0]?.term_id);
  const [graphList, setGraphList] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState(() => (uiDemoEnabled ? DEMO_JOB : null));
  const [selectedTermId, setSelectedTermId] = useState(null);
  const [pollError, setPollError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submitInFlightRef = useRef(false);
  const composingRef = useRef(false);
  const [historyTurnId, setHistoryTurnId] = useState(null);
  const [historyState, setHistoryState] = useState({ loading: false, error: "" });
  const gallerySelectionRef = useRef(null);
  if (!gallerySelectionRef.current) gallerySelectionRef.current = createGallerySelection({
    onJob: setJob, onSelection: setHistoryTurnId, onState: setHistoryState,
  });
  const [turns, setTurns] = useState(() => uiDemoEnabled
    ? [{ id: "demo-initial", request: DEMO_REQUEST_TEXT, job: DEMO_JOB, demo: true }] : []);
  const [conversationReady, setConversationReady] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const sessionIdRef = useRef(null);
  const sessionLoadRef = useRef(0);
  const [sessions, setSessions] = useState([]);
  const [sessionPage, setSessionPage] = useState({ hasMore: false, nextOffset: 0 });
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const sessionsGeneration = useRef(0);
  const [historyPage, setHistoryPage] = useState({ hasMore: false, nextBeforeJobId: null });
  const [olderLoading, setOlderLoading] = useState(false);
  const [olderError, setOlderError] = useState("");
  const historyController = useRef(null);
  const restoreController = useRef(null);
  const prependAnchor = useRef(null);
  const [referenceJob, setReferenceJob] = useState(null);
  const [persistentProfile, setPersistentProfile] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const deleteInFlightRef = useRef(false);
  const [deleteError, setDeleteError] = useState("");
  const [restoreError, setRestoreError] = useState("");
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [storageFailed, setStorageFailed] = useState(false);
  const demoStoreRef = useRef(null);
  const chatScrollRef = useRef(null);
  const [activeGalleryTermId, setActiveGalleryTermId] = useState(null);
  const [failedThumbnails, setFailedThumbnails] = useState({});
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobilePanel, setMobilePanel] = useState("reference");
  const [termGuide, setTermGuide] = useState(null);
  const [termSearch, setTermSearch] = useState(null);
  const termSearchControllerRef = useRef(null);
  const [sketchSearches, setSketchSearches] = useState({});
  const sketchControllersRef = useRef(new Map());
  const recoveryBudgetRef = useRef(createRecoveryBudget(0));
  const [recoveryClock, setRecoveryClock] = useState(0);
  const [previewPin, setPreviewPin] = useState(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const previewDialogRef = useRef(null);
  const previewTriggerRef = useRef(null);
  const [boardView, setBoardView] = useState("results");
  const menuButtonRef = useRef(null);
  const inputRef = useRef(null);
  const galleryRef = useRef(null);
  const submissionRef = useRef(null);
  const submissionRequestRef = useRef(null);
  const pollerRef = useRef(null);
  const selectedJobRef = useRef(null);
  const screenHistoryRef = useRef(null);
  const screenSnapshotRef = useRef(null);
  const screenGenerationRef = useRef(0);
  const mindMapSlots = useMemo(
    () => createMindMapSlots(historyTurnId ? resultTerms(job) : renderedResultTerms(job, turns, referenceJob)),
    [job, turns, historyTurnId, referenceJob],
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
  const galleryTerm = galleryRows.find((row) => row.term.term_id === activeGalleryTermId)?.term || galleryRows[0]?.term || null;
  const queryTerm = ["results", "term-results"].includes(boardView) && hasGalleryRows ? galleryTerm : homeTerm;
  const showingGraph = !(boardView === "results" && historyTurnId) && !( ["results", "term-results"].includes(boardView) && hasGalleryRows );
  const recommendedSearchQuery = showingGraph && graphTermIds.length
    ? combineRecommendedSearchQueries(HOME_TERMS.filter(term => graphTermIds.includes(term.term_id)))
    : getRecommendedSearchQuery(queryTerm);
  const pendingTurnIds = turns.filter(isTurnPending).map((turn) => `${turn.id}:${turn.screen_generation ?? ""}`).join(",");
  const conversationBusy = !conversationReady || isSubmitting || Boolean(pendingTurnIds) || Boolean(deletingId);
  const requestLength = countCharacters(requestText);
  const inputError = error || (requestLength > 500 ? validateRequestText(requestText) : "");
  screenSnapshotRef.current = { screenGeneration: screenGenerationRef.current, boardView, requestText, graphTermIds, graphFocusId, graphList, mobilePanel, job, historyTurnId,
    termSearch, termGuide, sessionId, turns, historyPage, referenceJob, activeGalleryTermId, selectedTermId,
    sketchSearches, failedThumbnails, error, pollError, restoreError, conversationReady, isSubmitting,
    recoveryBudget: recoveryBudgetRef.current };
  if (!submissionRef.current) submissionRef.current = createSubmissionController();

  useEffect(() => {
    if (!uiDemoEnabled) return;
    let storage;
    try { storage = window.localStorage; } catch { storage = null; }
    demoStoreRef.current = createDemoSessionStore(storage);
    showDemoSession(demoStoreRef.current.current());
  }, []);

  useEffect(() => {
    if (uiDemoEnabled) return;
    const controller = new AbortController();
    cancelHistory();
    restoreController.current = controller;
    const loadId = ++sessionLoadRef.current;
    gallerySelectionRef.current.reset(sessionIdRef.current);
    setRestoreError("");
    setConversationReady(false);
    ensureLocalProfile({ signal: controller.signal }).then((persistent) => {
      if (controller.signal.aborted) return;
      setPersistentProfile(persistent);
      refreshSessions();
      return restoreConversation({ signal: controller.signal, sessionId: sessionIdRef.current || undefined });
    }).then((restored) => {
      if (!restored || controller.signal.aborted || loadId !== sessionLoadRef.current) return;
      setSessionId(restored.sessionId);
      sessionIdRef.current = restored.sessionId;
      if (restored.session?.created_at) setSessions(current => mergeSessions(current, [restored.session]));
      setHistoryPage(restored);
      setReferenceJob(restored.previousReferenceJob);
      setTurns(restored.turns);
      gallerySelectionRef.current.reset(restored.sessionId);
      gallerySelectionRef.current.live(restored.referenceJob || restored.turns.at(-1)?.job || null, restored.sessionId);
      setConversationReady(true);
    }).catch(() => { if (!controller.signal.aborted && loadId === sessionLoadRef.current) setRestoreError(RESTORE_ERROR); });
    return () => controller.abort();
  }, [restoreAttempt]);

  function showDemoSession(session) {
    sessionIdRef.current = session.session_id;
    setSessionId(session.session_id);
    setSessions(demoStoreRef.current.list());
    setTurns(session.turns);
    gallerySelectionRef.current.reset(session.session_id);
    gallerySelectionRef.current.live(session.turns.at(-1)?.job || null, session.session_id);
    setStorageFailed(demoStoreRef.current.storageFailed);
    setConversationReady(true);
  }

  useLayoutEffect(() => {
    resizeComposerInput(inputRef.current, {
      viewportHeight: window.visualViewport?.height || window.innerHeight,
      scrollContainer: chatScrollRef.current,
    });
  }, [requestText, mobilePanel]);

  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const container = chatScrollRef.current;
    const anchor = container && createScrollEndAnchor(container);
    const resize = () => {
      resizeComposerInput(input, {
        viewportHeight: window.visualViewport?.height || window.innerHeight,
        scrollContainer: container,
      });
      anchor?.onResize();
    };
    let width = input.clientWidth;
    const observer = new ResizeObserver(() => {
      if (input.clientWidth !== width) { width = input.clientWidth; resize(); }
    });
    observer.observe(input);
    const endObserver = new ResizeObserver(() => anchor?.onResize());
    if (container) {
      container.addEventListener("scroll", anchor.onScroll, { passive: true });
      endObserver.observe(container);
    }
    window.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("resize", resize);
    return () => {
      observer.disconnect();
      endObserver.disconnect();
      container?.removeEventListener("scroll", anchor.onScroll);
      window.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("resize", resize);
    };
  }, []);

  useLayoutEffect(() => {
    const container = chatScrollRef.current;
    if (!container) return;
    if (prependAnchor.current) {
      const anchor = prependAnchor.current;
      container.scrollTop = anchor.top + container.scrollHeight - anchor.height;
      prependAnchor.current = null;
    } else container.scrollTop = container.scrollHeight;
  }, [turns, termGuide, mobilePanel]);

  function cancelHistory() {
    historyController.current?.abort();
    restoreController.current?.abort();
    prependAnchor.current = null;
    setOlderLoading(false);
    setOlderError("");
    setHistoryPage({ hasMore: false, nextBeforeJobId: null });
    setReferenceJob(null);
  }

  async function refreshSessions() {
    const generation = ++sessionsGeneration.current;
    setSessionsLoading(true);
    try {
      const page = await listConversationPage();
      if (generation !== sessionsGeneration.current) return;
      setSessions(current => mergeSessions(current.filter(item => item.session_id === sessionIdRef.current), page.items));
      setSessionPage(page);
    } catch { if (generation === sessionsGeneration.current) setDeleteError(RESTORE_ERROR); }
    finally { if (generation === sessionsGeneration.current) setSessionsLoading(false); }
  }
  async function loadMoreSessions() {
    if (sessionsLoading) return;
    const generation = sessionsGeneration.current;
    setSessionsLoading(true);
    try {
      const page = await listConversationPage({ offset: sessionPage.nextOffset });
      if (generation !== sessionsGeneration.current) return;
      setSessions(current => mergeSessions(current, page.items));
      setSessionPage(page);
    } catch { if (generation === sessionsGeneration.current) setDeleteError(RESTORE_ERROR); }
    finally { if (generation === sessionsGeneration.current) setSessionsLoading(false); }
  }
  async function loadOlder() {
    if (olderLoading || !historyPage.hasMore) return;
    const generation = sessionLoadRef.current;
    const id = sessionIdRef.current;
    historyController.current?.abort();
    const controller = new AbortController();
    historyController.current = controller;
    setOlderLoading(true); setOlderError("");
    try {
      const page = await loadOlderConversation({ sessionId: id, beforeJobId: historyPage.nextBeforeJobId, signal: controller.signal });
      if (controller.signal.aborted || generation !== sessionLoadRef.current || id !== sessionIdRef.current) return;
      const container = chatScrollRef.current;
      if (container) prependAnchor.current = { top: container.scrollTop, height: container.scrollHeight };
      setTurns(current => mergeHistoryTurns(current, page.turns));
      setHistoryPage(page);
    } catch { if (!controller.signal.aborted && generation === sessionLoadRef.current) setOlderError(RESTORE_ERROR); }
    finally { if (!controller.signal.aborted && generation === sessionLoadRef.current) setOlderLoading(false); }
  }
  useEffect(() => () => { historyController.current?.abort(); restoreController.current?.abort(); ++sessionsGeneration.current; }, []);

  useEffect(() => {
    if (uiDemoEnabled || !conversationReady || !pendingTurnIds) return;
    const latestId = turns.at(-1)?.id;
    const activeSessionId = sessionIdRef.current;
    const activeScreenId = turns.at(-1)?.screen_generation ?? screenGenerationRef.current;
    const poller = resumeConversation(turns, { onUpdate: (turn) => {
      if (sessionIdRef.current !== activeSessionId || activeSessionId !== turn.job?.session_id) return;
      setTurns((entries) => upsertTurn(entries, turn));
      if (turn.job?.job_status === "completed") refreshSessions();
      if (turn.id === latestId && activeScreenId === screenGenerationRef.current) {
        gallerySelectionRef.current.live(turn.job, activeSessionId);
        if (resultTerms(turn.job).length) {
          setBoardView("results");
          setMobilePanel("reference");
          setTermSearch(null);
          setTermGuide(null);
        }
      }
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
  }, [pendingTurnIds, conversationReady, sessionId]);

  useEffect(() => {
    screenHistoryRef.current = createScreenHistory({history:window.history,target:window,
      read:()=>screenSnapshotRef.current,restore:restoreScreen,
      keyForSnapshot:snapshot=>snapshot.boardView === "home" || (snapshot.boardView === "results" && !snapshot.job && !snapshot.turns.length && !snapshot.isSubmitting)
        ? "home" : snapshot.boardView === "term-results" ? `term:${snapshot.termSearch?.term?.term_id}`
        : snapshot.historyTurnId ? `turn:${snapshot.sessionId}:${snapshot.historyTurnId}`
        : snapshot.job ? `result:${snapshot.sessionId}:${snapshot.job.job_id || "demo"}` : null,
      fallback:()=>({boardView:"home",requestText:"",graphTermIds:[],graphFocusId:HOME_TERMS[0]?.term_id,graphList:false,mobilePanel:"reference",
        job:null,historyTurnId:null,termSearch:null,termGuide:null,sessionId:null,turns:[],
        historyPage:{hasMore:false,nextBeforeJobId:null},referenceJob:null,activeGalleryTermId:null,
        sketchSearches:{},failedThumbnails:{},selectedTermId:null,error:"",pollError:"",restoreError:"",conversationReady:true})});
    return () => {
      screenHistoryRef.current?.dispose();
      screenHistoryRef.current = null;
      gallerySelectionRef.current.dispose();
    };
  }, []);

  useLayoutEffect(() => { screenHistoryRef.current?.capture(); });

  function visitScreen(key) { ++screenGenerationRef.current; screenHistoryRef.current?.visit(key); }

  function cancelSubmission() {
    submissionRequestRef.current?.abort();
    submissionRequestRef.current = null;
    submissionRef.current = createSubmissionController();
    submitInFlightRef.current = false;
    setIsSubmitting(false);
  }

  function restoreScreen(snapshot) {
    ++screenGenerationRef.current;
    cancelSubmission();
    cancelHistory();
    ++sessionLoadRef.current;
    if(sessionIdRef.current !== snapshot.sessionId)pollerRef.current?.stop();
    termSearchControllerRef.current?.abort();
    resetSketchSearches(false);
    previewDialogRef.current?.close();
    setPreviewPin(null);
    setMenuOpen(false);
    sessionIdRef.current = snapshot.sessionId;
    if(uiDemoEnabled && snapshot.sessionId)demoStoreRef.current?.select(snapshot.sessionId);
    setSessionId(snapshot.sessionId);
    selectedJobRef.current = snapshot.job;
    setSelectedTermId(snapshot.selectedTermId);
    gallerySelectionRef.current.restore(snapshot.job, snapshot.historyTurnId, snapshot.sessionId);
    setHistoryState({loading:false,error:snapshot.historyTurnId && !snapshot.job ? "검색 기록을 불러오지 못했습니다. 다시 시도해 주세요." : ""});
    setBoardView(snapshot.boardView);
    setRequestText(snapshot.requestText);
    setGraphTermIds(snapshot.graphTermIds);
    setGraphFocusId(snapshot.graphFocusId || HOME_TERMS[0]?.term_id);
    setGraphList(Boolean(snapshot.graphList));
    setMobilePanel(snapshot.mobilePanel);
    setTurns(snapshot.turns.map(turn => isTurnPending(turn) && turn.screen_generation === snapshot.screenGeneration
      ? { ...turn, screen_generation: screenGenerationRef.current } : turn));
    setHistoryPage(snapshot.historyPage);
    setReferenceJob(snapshot.referenceJob);
    setActiveGalleryTermId(snapshot.activeGalleryTermId);
    setSketchSearches(Object.fromEntries(Object.entries(snapshot.sketchSearches).map(([id,value])=>
      [id,value.loading?{...value,loading:false,error:"검색이 중단되었습니다. 다시 찾아 주세요."}:value])));
    setFailedThumbnails(snapshot.failedThumbnails);
    setTermGuide(snapshot.termGuide);
    setTermSearch(snapshot.termSearch?.loading ? {...snapshot.termSearch,loading:false,error:"검색이 중단되었습니다. 다시 찾아 주세요."} : snapshot.termSearch);
    setError(snapshot.error);
    setPollError(snapshot.pollError);
    setRestoreError(snapshot.conversationReady ? snapshot.restoreError : RESTORE_ERROR);
    setConversationReady(true);
    if(snapshot.recoveryBudget)recoveryBudgetRef.current=snapshot.recoveryBudget;
  }

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
    setActiveGalleryTermId((current) => (
      galleryRows.some((row) => row.term.term_id === current) ? current : galleryRows[0]?.term.term_id || null
    ));
  }, [galleryRows]);

  useEffect(() => {
    if (!["results", "term-results"].includes(boardView)) return;
    const syncMobileGallery = () => {
      if (window.matchMedia("(max-width: 760px)").matches && galleryRef.current) {
        syncGalleryTerm(galleryRef.current);
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

  async function handleSubmit(event) {
    event.preventDefault();
    if (composingRef.current) return;
    await submit(requestText);
  }

  function openTurn(turn) {
    if (!conversationReady || turn.job?.job_status !== "completed") return;
    visitScreen(`turn:${turn.job.session_id || sessionIdRef.current}:${turn.id}`);
    termSearchControllerRef.current?.abort();
    resetSketchSearches(false);
    setTermSearch(null);
    setTermGuide(null);
    previewDialogRef.current?.close();
    setPreviewPin(null);
    setBoardView("results");
    setMobilePanel("reference");
    gallerySelectionRef.current.open(turn);
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
  }

  async function openTermSearch(term) {
    visitScreen(`term:${term.term_id}`);
    gallerySelectionRef.current.reset(sessionIdRef.current);
    setTermGuide(term);
    resetSketchSearches();
    termSearchControllerRef.current?.abort();
    const controller = new AbortController();
    termSearchControllerRef.current = controller;
    setSelectedTermId(term.term_id);
    setActiveGalleryTermId(term.term_id);
    setFailedThumbnails({});
    setTermSearch({ term: { ...term, pins: term.pins || [], reason_codes: [] }, loading: true });
    setBoardView("term-results");
    setMobilePanel("conversation");
    try {
      const result = uiDemoEnabled
        ? demoTerm(term.term_id)
        : await searchFixedTerm(term, { signal: controller.signal });
      if (!controller.signal.aborted) setTermSearch({ term: term.pins?.some(showThumbnail) ? applySketchResult(term, result) : result, loading: false });
    } catch (error) {
      if (!controller.signal.aborted) setTermSearch({
        term: { ...term, pins: term.pins || [], reason_codes: ["PIN_SEARCH_UNAVAILABLE"] },
        loading: false, error: error.message,
      });
    }
  }

  function resetSketchSearches(resetBudget = true) {
    for (const controller of sketchControllersRef.current.values()) controller.abort();
    sketchControllersRef.current.clear();
    setSketchSearches({});
    if (resetBudget) recoveryBudgetRef.current = createRecoveryBudget(recoveryBudgetRef.current.generation + 1);
  }

  async function searchCategory(term, suffix, recover = false, recoveryKind = 'manual') {
    if (uiDemoEnabled) {
      setSketchSearches((current) => ({ ...current, [term.term_id]: {
        suffix, error: "데모에서는 실시간 이미지 검색을 제공하지 않습니다.",
      } }));
      return;
    }
    if (sketchControllersRef.current.has(term.term_id)) return;
    const generation = recoveryBudgetRef.current.generation;
    if (recover) {
      const claim = claimRecovery(recoveryBudgetRef.current, { generation, termId: term.term_id, kind: recoveryKind });
      if (!claim.allowed) return;
      recoveryBudgetRef.current = claim.budget;
    } else {
      const cards = { ...recoveryBudgetRef.current.cards };
      delete cards[term.term_id];
      recoveryBudgetRef.current = { ...recoveryBudgetRef.current, cards };
    }
    const controller = new AbortController();
    sketchControllersRef.current.set(term.term_id, controller);
    setSketchSearches((current) => ({ ...current, [term.term_id]: { ...current[term.term_id], loading: true, pendingSuffix: suffix, error: null } }));
    let recoveryResult;
    try {
      const failedIds = Object.keys(failedThumbnails).filter(key => key.startsWith(`${term.term_id}:`)).map(key => key.slice(term.term_id.length + 1));
      const result = recover ? await searchFixedTerm(term, { suffix, signal: controller.signal, maxRetries: 0,
        excludePinIds: [...failedIds, ...(term.pins || []).map(pin => pin.pin_id)] }) : null;
      recoveryResult = result;
      const updatedTerm = recover
        ? applyPreviewRecovery(term, result, failedIds)
        : await searchTermMode(term, suffix, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setSketchSearches((current) => ({ ...current, [term.term_id]: { term: updatedTerm, suffix } }));
        if (!recover) setFailedThumbnails((current) => Object.fromEntries(Object.entries(current)
          .filter(([key]) => !key.startsWith(`${term.term_id}:`))));
      }
    } catch (error) {
      recoveryResult ||= error;
      if (!controller.signal.aborted) setSketchSearches((current) => ({
        ...current, [term.term_id]: { ...current[term.term_id], loading: false, pendingSuffix: null, error: error.message },
      }));
    } finally {
      if (recover) recoveryBudgetRef.current = finishRecovery(recoveryBudgetRef.current, {
        generation, termId: term.term_id, retryAfterSeconds: recoveryResult?.retry_after_seconds,
        restricted: recoveryResult?.search_failure === 'access_restricted',
      });
      if (sketchControllersRef.current.get(term.term_id) === controller) sketchControllersRef.current.delete(term.term_id);
    }
  }

  useEffect(() => {
    if (uiDemoEnabled || !['results', 'term-results'].includes(boardView)) return;
    for (const {term,pins} of galleryRows) {
      if (pins.some(pin => !showThumbnail(pin) || failedThumbnails[`${term.term_id}:${pin.pin_id}`])) {
        const restricted = term.search_failure === 'access_restricted' || pins.some(pin => pin.failure_reason === 'access_restricted');
        const retryAfterSeconds = Math.max(term.retry_after_seconds || 0, ...pins.map(pin => pin.retry_after_seconds || 0));
        if (restricted || retryAfterSeconds > 0) {
          const claim = claimRecovery(recoveryBudgetRef.current, {generation: recoveryBudgetRef.current.generation, termId: term.term_id});
          if (claim.allowed) {
            recoveryBudgetRef.current = finishRecovery(claim.budget, {generation: claim.budget.generation,
              termId: term.term_id, restricted, retryAfterSeconds});
            setRecoveryClock(Date.now());
          }
          continue;
        }
        // One automatic attempt per explicit search generation; no effect-driven retry loop.
        searchCategory(term, sketchSearches[term.term_id]?.suffix || 'drawing', true, 'auto');
      }
    }
  }, [galleryRows, failedThumbnails, boardView]);

  useEffect(() => {
    if (!Object.values(recoveryBudgetRef.current.cards).some(card => card.retryAt > Date.now())) return;
    const timer = setInterval(() => setRecoveryClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [recoveryClock, sketchSearches, galleryRows]);

  async function submit(text) {
    if (deleteInFlightRef.current || conversationBusy || submitInFlightRef.current || submissionRef.current.isPending()) return;

    const validationError = validateRequestText(text);
    if (validationError) {
      setError(validationError);
      return;
    }
    visitScreen(`request:${crypto.randomUUID()}`);
    const submitLoadId = sessionLoadRef.current;
    const submitScreenId = screenGenerationRef.current;
    const submitRequest = new AbortController();
    submissionRequestRef.current = submitRequest;
    const submissionController = submissionRef.current;
    submitInFlightRef.current = true;
    gallerySelectionRef.current.begin(sessionIdRef.current);
    setMobilePanel("conversation");
    setTermGuide(null);

    if (uiDemoEnabled) {
      if(!sessionIdRef.current)showDemoSession(demoStoreRef.current.create());
      const turn = demoStoreRef.current.submit(text);
      if (turn) {
        showDemoSession(demoStoreRef.current.current());
        setBoardView("results");
        setRequestText("");
        setError("");
      } else {
        setError(DEMO_INPUT_ERROR);
        setMobilePanel("conversation");
      }
      queueMicrotask(() => { if(submissionRequestRef.current === submitRequest) { submissionRequestRef.current = null; submitInFlightRef.current = false; } });
      return;
    }

    pollerRef.current?.stop();
    setIsSubmitting(true);
    setError("");
    setPollError("");
    try {
      let activeSession = sessionIdRef.current;
      if (!activeSession) {
        const created = await createConversation({signal:submitRequest.signal});
        if(submitLoadId !== sessionLoadRef.current || submitScreenId !== screenGenerationRef.current)return;
        activeSession = created.session_id;
        setSessions((items) => [created, ...items.filter((item) => item.session_id !== created.session_id)]);
      }
      setSessionId(activeSession);
      sessionIdRef.current = activeSession;
      gallerySelectionRef.current.begin(activeSession);
      const result = await submissionController.submit(text, { sessionId: activeSession, signal:submitRequest.signal });
      if(submitLoadId !== sessionLoadRef.current || submissionRequestRef.current !== submitRequest)return;
      if (result.ok) {
        setSessions((items) => {
          const selected = items.find((item) => item.session_id === activeSession);
          return selected ? [selected, ...items.filter((item) => item.session_id !== activeSession)] : items;
        });
        setTurns((entries) => upsertTurn(entries, { id: result.jobId, request: text, screen_generation: submitScreenId,
          job: { job_id: result.jobId, session_id: activeSession,
            job_status: "queued", poll_after_ms: result.pollAfterMs }, demo: false }));
        refreshSessions();
        if(submitScreenId === screenGenerationRef.current)setRequestText("");
      }
      else {
        if(submitScreenId !== screenGenerationRef.current)return;
        setError(result.error);
        setMobilePanel("conversation");
      }
    } catch {
      if(submitLoadId !== sessionLoadRef.current || submitScreenId !== screenGenerationRef.current)return;
      setError("대화 요청을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      setMobilePanel("conversation");
    } finally {
      if(submissionRequestRef.current === submitRequest) {
        submissionRequestRef.current = null;
        submitInFlightRef.current = false;
        setIsSubmitting(false);
      }
    }
  }

  function handleGalleryScroll(event) {
    syncGalleryTerm(event.currentTarget);
  }

  function syncGalleryTerm(gallery) {
    const mobile = window.matchMedia("(max-width: 760px)").matches;
    const bounds = gallery.getBoundingClientRect();
    const headerHeight = gallery.closest(".reference-board").querySelector(".board-header").getBoundingClientRect().height;
    if (mobile && (bounds.top > window.innerHeight || bounds.bottom < headerHeight)) return;
    const galleryTop = mobile ? headerHeight : bounds.top;
    const closestRow = galleryRows.reduce((closest, row) => {
      const element = Array.from(gallery.querySelectorAll("[data-gallery-term-id]")).find((element) => element.dataset.galleryTermId === row.term.term_id);
      if (!element) return closest;
      const distance = Math.abs(element.getBoundingClientRect().top - galleryTop);
      return !closest || distance < closest.distance ? { termId: row.term.term_id, distance } : closest;
    }, null);

    if (closestRow) {
      setActiveGalleryTermId((current) => current === closestRow.termId ? current : closestRow.termId);
    }
  }

  function navigateBoard(view, record = true) {
    if(record)visitScreen(view);
    cancelSubmission();
    gallerySelectionRef.current.reset(sessionIdRef.current);
    previewDialogRef.current?.close();
    setPreviewPin(null);
    setTermSearch(null);
    setTermGuide(null);
    resetSketchSearches(false);
    termSearchControllerRef.current?.abort();
    setBoardView(view);
    setMobilePanel("reference");
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  }

  async function openSession(session) {
    if (deleteInFlightRef.current || submitInFlightRef.current || isSubmitting) return;
    setMenuOpen(false);
    if (session.session_id === sessionIdRef.current && boardView === "results") return;
    visitScreen(`session:${session.session_id}`);
    const navigationId = screenGenerationRef.current;
    if (uiDemoEnabled) {
      const selected = demoStoreRef.current.select(session.session_id);
      if (!selected) return;
      navigateBoard("results", false);
      showDemoSession(selected);
      setError("");
      return;
    }
    cancelHistory();
    const loadId = ++sessionLoadRef.current;
    gallerySelectionRef.current.reset(session.session_id);
    setTermSearch(null);
    previewDialogRef.current?.close();
    setPreviewPin(null);
    setTermGuide(null);
    setMenuOpen(false);
    resetSketchSearches();
    termSearchControllerRef.current?.abort();
    pollerRef.current?.stop();
    setConversationReady(false);
    setRestoreError("");
    setPollError("");
    setSessionId(session.session_id);
    sessionIdRef.current = session.session_id;
    setSessions((items) => [session, ...items.filter((item) => item.session_id !== session.session_id)]);
    refreshSessions();
    setTurns([]);
    setJob(null);
    try {
      const controller = new AbortController();
      restoreController.current = controller;
      const restored = await restoreConversation({ sessionId: session.session_id, signal: controller.signal });
      if (loadId !== sessionLoadRef.current) return;
      if (restored.session?.created_at) setSessions(current => mergeSessions(current, [restored.session]));
      setHistoryPage(restored);
      setReferenceJob(restored.previousReferenceJob);
      setTurns(restored.turns);
      gallerySelectionRef.current.live(restored.referenceJob || restored.turns.at(-1)?.job || null, restored.sessionId);
      setConversationReady(true);
      setActiveGalleryTermId(null);
      if(navigationId === screenGenerationRef.current) {
        setBoardView("results");
        setMobilePanel("reference");
      }
    } catch {
      if (loadId === sessionLoadRef.current) {
        setRestoreError(RESTORE_ERROR);
        setConversationReady(true);
      }
    }
  }

  async function startNewSession() {
    if (deleteInFlightRef.current || submitInFlightRef.current || isSubmitting) return;
    visitScreen(`new:${crypto.randomUUID()}`);
    const navigationId = screenGenerationRef.current;
    if (uiDemoEnabled) {
      navigateBoard("results", false);
      showDemoSession(demoStoreRef.current.create());
      setRequestText("");
      setError("");
      setMobilePanel("conversation");
      return;
    }
    cancelHistory();
    const loadId = ++sessionLoadRef.current;
    gallerySelectionRef.current.reset(null);
    sessionIdRef.current = null;
    setSessionId(null);
    setTurns([]);
    setJob(null);
    setTermSearch(null);
    setTermGuide(null);
    setBoardView("results");
    resetSketchSearches();
    termSearchControllerRef.current?.abort();
    previewDialogRef.current?.close();
    setPreviewPin(null);
    pollerRef.current?.stop();
    setConversationReady(false);
    setRestoreError("");
    try {
      const created = await createConversation();
      if (loadId !== sessionLoadRef.current) return;
      setSessions((items) => [created, ...items.filter((item) => item.session_id !== created.session_id)]);
      setSessionId(created.session_id);
      sessionIdRef.current = created.session_id;
      refreshSessions();
      gallerySelectionRef.current.reset(created.session_id);
      setTurns([]);
      setJob(null);
      setPollError("");
      setConversationReady(true);
      setRestoreError("");
      setTermGuide(null);
      if(navigationId === screenGenerationRef.current) {
        setBoardView("results");
        setMobilePanel("reference");
      }
      setMenuOpen(false);
    } catch {
      if (loadId === sessionLoadRef.current) {
        setConversationReady(true);
        setRestoreError("새 세션을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.");
      }
    }
  }

  async function removeSession(session) {
    if (deleteInFlightRef.current || submitInFlightRef.current || !conversationReady) return;
    if (!window.confirm(DELETE_CONFIRM)) return;
    deleteInFlightRef.current = true;
    setDeletingId(session.session_id);
    setDeleteError("");
    try {
      if (uiDemoEnabled) {
        showDemoSession(demoStoreRef.current.remove(session.session_id));
        screenHistoryRef.current?.forgetSession(session.session_id);
        navigateBoard("results", false);
      } else {
        await deleteConversation(session.session_id);
        screenHistoryRef.current?.forgetSession(session.session_id);
        setSessions(items => items.filter(item => item.session_id !== session.session_id));
        refreshSessions();
        if (sessionIdRef.current === session.session_id) {
          cancelHistory();
          ++sessionLoadRef.current;
          pollerRef.current?.stop();
          sessionIdRef.current = null;
          setSessionId(null);
          setTurns([]);
          setJob(null);
          gallerySelectionRef.current.reset(null);
          navigateBoard("results", false);
          setRequestText("");
          setError("");
          setPollError("");
          setRestoreError("");
          setMobilePanel("conversation");
        }
      }
    } catch (error) {
      setDeleteError(error.message || "대화를 삭제하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      deleteInFlightRef.current = false;
      setDeletingId(null);
    }
  }

  return (
    <main className="workspace" data-mobile-panel={mobilePanel}>
      <nav className="mobile-workspace-nav" aria-label="작업 화면">
        <HistoryLogo open={menuOpen} onClick={toggleMenu} />
        <button type="button" aria-pressed={mobilePanel === "reference"} aria-controls="reference-panel"
          onClick={() => setMobilePanel("reference")}>레퍼런스</button>
        <button type="button" aria-pressed={mobilePanel === "conversation"} aria-controls="conversation-panel"
          onClick={() => setMobilePanel("conversation")}>대화</button>
      </nav>
      <HistoryDrawer open={menuOpen} onClose={() => setMenuOpen(false)} triggerRef={menuButtonRef}>
        {uiDemoEnabled && <span className="demo-badge">{DEMO_NOTICE}</span>}
        <nav className="history-sidebar-list" aria-label="세션 목록">
          <p className="conversation-notice">{uiDemoEnabled
            ? "고정 샘플 대화는 이 브라우저에만 저장됩니다. 최대 10개 세션·총 50개 답변을 보관하며 서버로 보내지 않습니다. 개인·민감 정보는 입력하지 마세요."
            : persistentProfile ? "이 PC의 대화는 직접 삭제할 때까지 보관합니다. 로컬 프로필로 기록을 복원합니다." : "같은 브라우저의 쿠키로 최근 대화를 복원합니다. 쿠키 삭제·대화 만료 후에는 복원되지 않습니다."}</p>
          <button className="history-sidebar-entry" type="button" onClick={() => navigateBoard("home")}>홈 · 용어 그래프</button>
          <button className="history-sidebar-entry" type="button" disabled={!conversationReady || isSubmitting || Boolean(deletingId)} onClick={startNewSession}>새 세션</button>
          {sessions.map((session) => (
              <div className="history-sidebar-row" key={session.session_id}>
              <button className="history-sidebar-entry" type="button"
                disabled={isSubmitting || Boolean(deletingId)} title={`${sessionTitle(session)} · ${new Date(session.created_at).toLocaleString("ko-KR")}`}
                aria-current={sessionId === session.session_id ? "page" : undefined}
                onClick={() => openSession(session)}>
                <span className="history-sidebar-title">{uiDemoEnabled ? "샘플 · " : ""}{sessionTitle(session)}</span>
              </button>
              <button className="history-delete" type="button"
                aria-label={`${sessionTitle(session)} 대화 삭제`}
                disabled={!conversationReady || isSubmitting || Boolean(deletingId) || (sessionId === session.session_id && Boolean(pendingTurnIds))}
                onClick={() => removeSession(session)}>{deletingId === session.session_id ? "삭제 중…" : "삭제"}</button>
              </div>
            ))}
          {!uiDemoEnabled && sessionPage.hasMore && <button type="button" className="history-sidebar-entry" disabled={sessionsLoading} onClick={loadMoreSessions}>대화 더 불러오기</button>}
          {!uiDemoEnabled && !sessions.length && <p className="history-sidebar-empty">아직 대화 세션이 없습니다.</p>}
          {deleteError && <p className="form-error" role="alert">{deleteError}</p>}
        </nav>
      </HistoryDrawer>
      <section id="reference-panel" className="reference-board" aria-label="레퍼런스">
        <header className="board-header">
          {uiDemoEnabled && <span className="demo-badge">{DEMO_NOTICE}</span>}
          <HistoryLogo className="desktop-history-logo" open={menuOpen} onClick={toggleMenu} />
          {!uiDemoEnabled && recommendedSearchQuery && (
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
        {boardView === "results" && historyState.loading ? (
          <div className="board-search-loading"><LoadingIndicator label="이 답변의 레퍼런스를 불러오는 중…" /></div>
        ) : boardView === "results" && historyState.error ? (
          <div className="board-empty" role="alert"><p>{historyState.error}</p>
            <button type="button" onClick={() => {
              const turn = turns.find((entry) => entry.id === historyTurnId);
              if (turn) openTurn(turn);
            }}>다시 불러오기</button>
            <button type="button" onClick={() => navigateBoard("home")}>용어 둘러보기</button>
          </div>
        ) : ["results", "term-results"].includes(boardView) && hasGalleryRows ? (
          <div className="pin-gallery" ref={galleryRef} data-single={galleryRows.length === 1}
            aria-label="카테고리별 Pinterest 핀 썸네일" onScroll={handleGalleryScroll}>
            <button className="gallery-back-button" type="button" onClick={() => navigateBoard("home")}>← 용어 둘러보기</button>
            {galleryRows.map(({ role, roleLabel, term, pins }) => (
              <section className="pin-gallery-row" data-gallery-role={role} data-gallery-term-id={term.term_id} key={term.term_id} aria-label={`${roleLabel} 검색 결과`}>
                <div className="pin-gallery-toolbar">
                <button className="pin-gallery-heading" type="button"
                  aria-pressed={term.term_id === galleryTerm?.term_id}
                  aria-label={`${roleLabel} ${term.label_ko} 검색어 보기`}
                  onClick={() => { setSelectedTermId(term.term_id); setActiveGalleryTermId(term.term_id); }}>
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
                <p className="pin-result-count" role="status">이미지 {usableGalleryPins(pins, failedThumbnails, term.term_id).length} / 최대 8개</p>
                {recoveryBudgetRef.current.cards[term.term_id]?.auto &&
                  !recoveryBudgetRef.current.cards[term.term_id]?.manual &&
                  !recoveryBudgetRef.current.cards[term.term_id]?.restricted &&
                  usableGalleryPins(pins, failedThumbnails, term.term_id).length < 8 &&
                  <button type="button" disabled={Boolean(sketchSearches[term.term_id]?.loading) || recoveryBudgetRef.current.cards[term.term_id]?.retryAt > Date.now()}
                    onClick={() => searchCategory(term, sketchSearches[term.term_id]?.suffix || 'drawing', true)}>
                    {recoveryBudgetRef.current.cards[term.term_id]?.retryAt > Date.now()
                      ? `${Math.ceil((recoveryBudgetRef.current.cards[term.term_id].retryAt-Date.now())/1000)}초 후 추가로 찾기` : '이미지 추가로 찾기'}</button>}
                <MasonryGallery>
                  {boardView === "term-results" && termSearch?.loading && <ImageSearchLoading />}
                  {boardView === "term-results" && termSearch?.error && <p className="pin-unavailable" role="alert">{termSearch.error}</p>}
                  {roleNotice(term) && <p className="pin-unavailable" role="status">{roleNotice(term)}</p>}
                  {boardView === "term-results" && !termSearch?.loading && (termSearch?.error || roleNotice(term)) &&
                    <button type="button" onClick={() => openTermSearch(term)}>다시 찾기</button>}
                  {!pins.length && !roleNotice(term) && !(boardView === "term-results" && termSearch?.loading) && <p className="pin-unavailable">{uiDemoEnabled ? "데모에서는 실시간 이미지 검색을 제공하지 않습니다." : "표시할 핀이 없습니다."}</p>}
                  {usableGalleryPins(pins, failedThumbnails, term.term_id).map((pin, index) => (
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
                  ))}
                </MasonryGallery>
              </section>
            ))}
          </div>
        ) : boardView === "results" && historyTurnId ? (
          <div className="board-empty" role="status"><p>이 답변에는 표시할 레퍼런스가 없습니다.</p>
            <button type="button" onClick={() => navigateBoard("home")}>용어 둘러보기</button>
          </div>
        ) : hasTerms ? (
          <TermGraph terms={HOME_TERMS} selectedIds={graphTermIds}
            focusedId={graphFocusId} onFocus={setGraphFocusId} list={graphList} onListChange={setGraphList}
            onToggle={(id) => {setGraphTermIds((ids) => toggleTerm(ids, id));setGraphFocusId(id);}}
            onSearch={openTermSearch}
            onAdd={(terms) => {
              const next = appendTerms(requestText, terms);
              if (next === null) return false;
              setRequestText(next);
              setError("");
              setMobilePanel("conversation");
              inputRef.current?.focus();
              return true;
            }} />
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
          {uiDemoEnabled && <span className="demo-badge">{DEMO_NOTICE}</span>}
          <h2 id="prompt-title">UH케 그릴 건가요?</h2>
          {restoreError && <div role="alert"><p>{restoreError}</p>
            <button type="button" onClick={() => setRestoreAttempt((value) => value + 1)}>대화 다시 불러오기</button></div>}
          {storageFailed && <p className="form-error" role="status">브라우저 기록을 읽거나 쓰지 못했습니다. 일부 기록이 복원되지 않을 수 있지만 현재 대화는 계속 사용할 수 있습니다.</p>}
          {!uiDemoEnabled && historyPage.hasMore && <button type="button" disabled={olderLoading} onClick={loadOlder}>이전 대화 불러오기</button>}
          {olderError && <p role="alert">{olderError}</p>}
          <ConversationPanel key={sessionId || "no-session"} turns={turns} />
          <TermGuide term={termGuide} />
          {uiDemoEnabled && <div className="demo-scenarios" aria-label="대표 샘플 입력">
            <p>대표 예시를 선택한 뒤 전송해 보세요.</p>
            {DEMO_SCENARIOS.map(sample => <button type="button" key={sample.id}
              onClick={() => fillInput(sample.request)}>{sample.request}</button>)}
          </div>}
          {((!conversationReady && !restoreError) || isSubmitting) && <div className="receipt"><LoadingIndicator
            label={!conversationReady ? "대화를 불러오는 중…" : "요청을 보내는 중…"} /></div>}
          {pollError && <p className="form-error" role="alert">{pollError}</p>}
        </div>

        <form className="composer" onSubmit={handleSubmit} noValidate>
          <div className="composer-input-frame" data-invalid={Boolean(inputError)}>
          <textarea
            id="request-text"
            ref={inputRef}
            name="request_text"
            aria-label="캐릭터 설명"
            rows={1}
            value={requestText}
            disabled={conversationBusy}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => { composingRef.current = false; }}
            onChange={(event) => {
              setRequestText(event.target.value);
              if (error) setError("");
            }}
            onKeyDown={(event) => {
              if (shouldSubmitOnEnter(event, composingRef.current)) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="원하는 체형, 포즈, 구도을 적어 주세요"
            aria-invalid={Boolean(inputError)}
            aria-describedby={`request-limit${requestLength >= 450 ? " request-count" : ""}${inputError ? " request-error" : ""}`}
          />
            <button className="composer-submit" type="submit" aria-label="전송" aria-busy={isSubmitting}
              disabled={conversationBusy || Boolean(validateRequestText(requestText))}>
              <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m6 15 6-6 6 6" /></svg>
            </button>
          </div>
          <span id="request-limit" className="sr-only">최대 500자까지 입력할 수 있습니다.</span>
          {inputError && <p id="request-error" className="form-error" role="alert">{inputError}</p>}
          <div className="composer-footer">
            <span id="request-hint" className="input-hint">Enter로 검색 · Shift+Enter로 줄바꿈</span>
            {requestLength >= 450 && <span id="request-count" className="character-count" role="status">{requestLength} / 500</span>}
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

