"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  bindAccountQuotaDismissal,
  createAccountQuotaDisclosureState,
  reduceAccountQuotaDisclosure,
} from "../lib/account-quota-disclosure.mjs";

export default function AccountQuota() {
  const [usage, setUsage] = useState(null);
  const [role, setRole] = useState(null);
  const [state, setState] = useState("loading");
  const [expanded, updateDisclosure] = useReducer(
    reduceAccountQuotaDisclosure, undefined, createAccountQuotaDisclosureState,
  );
  const rootRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [usageResponse, authResponse] = await Promise.all([
        fetch("/api/account/usage", { credentials: "include", cache: "no-store" }),
        fetch("/api/auth/me", { credentials: "include", cache: "no-store" }),
      ]);
      if ([401, 404].includes(usageResponse.status)) {
        setState("hidden");
        return;
      }
      if (!usageResponse.ok) throw new Error("usage unavailable");
      const nextUsage = await usageResponse.json();
      const auth = authResponse.ok ? await authResponse.json() : null;
      setUsage(nextUsage);
      setRole(auth?.role || null);
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => {
    refresh();
    const onRefresh = () => {
      updateDisclosure({ type: "refresh" });
      refresh();
    };
    const onFocus = () => {
      updateDisclosure({ type: "navigate" });
      refresh();
    };
    window.addEventListener("account-quota-refresh", onRefresh);
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("account-quota-refresh", onRefresh);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  useEffect(() => {
    if (!expanded) return undefined;
    return bindAccountQuotaDismissal({
      documentTarget: document,
      windowTarget: window,
      root: rootRef.current,
      onDismiss: () => updateDisclosure({ type: "dismiss" }),
    });
  }, [expanded]);

  if (state === "hidden") return null;
  if (state === "loading") return <span className="account-quota" role="status">AI 이용량 확인 중…</span>;
  if (state === "error") return <button className="account-quota quota-error" type="button" onClick={refresh}>AI 이용량 다시 확인</button>;
  const availability = usage.unlimited ? "이용 가능 무제한" : `이용 가능 ${usage.remaining}회`;
  return <aside ref={rootRef} className="account-quota" data-expanded={expanded}
    aria-label="계정 AI 요청 횟수">
    <button className="account-quota-summary" type="button" aria-expanded={expanded}
      aria-controls="account-quota-details" onClick={() => updateDisclosure({ type: "toggle" })}>
      <span>계정</span>
      <strong className={!usage.unlimited && usage.remaining === 0 ? "quota-exhausted" : ""}>
        {availability}
      </strong>
      <span aria-hidden="true">{expanded ? "▴" : "▾"}</span>
    </button>
    {expanded && <div id="account-quota-details" className="account-quota-details">
      <span>{usage.unlimited
        ? `앱 한도 무제한 · 사용 완료 ${usage.charged} · 처리 중 ${usage.reserved}`
        : `누적 지급 ${usage.limit} · 사용 완료 ${usage.charged} · 처리 중 ${usage.reserved}`}</span>
      <small>새 대화에서도 총량은 유지되며, 고정 안내와 이미지 재검색은 차감되지 않습니다.</small>
      <a href="/api/auth/google/start">Google 계정 변경</a>
      {role === "admin" && <a href="/admin">초대·사용량 관리</a>}
      <button className="account-quota-close" type="button"
        onClick={() => updateDisclosure({ type: "dismiss" })}>닫기</button>
    </div>}
  </aside>;
}
