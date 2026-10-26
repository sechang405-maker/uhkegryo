"use client";

import { useEffect, useState } from "react";

export default function AccountTransferPage() {
  const [details, setDetails] = useState(null);
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("error") === "already-bound") {
      setError("선택한 Google 계정은 이미 다른 이용 계정에 연결되어 있습니다.");
      setState("error");
      return;
    }
    fetch("/api/auth/identity-transfer/status", { credentials: "include", cache: "no-store" })
      .then(async response => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "계정 이전 정보를 확인하지 못했습니다.");
        setDetails(body);
        setState("ready");
      })
      .catch(cause => { setError(cause.message); setState("error"); });
  }, []);

  async function requestTransfer() {
    if (state !== "ready") return;
    setState("submitting"); setError("");
    try {
      const response = await fetch("/api/auth/identity-transfer/request", {
        method: "POST",
        credentials: "include",
        headers: { "x-auth-action": "request-transfer" },
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "계정 이전 요청을 만들지 못했습니다.");
      setState("pending");
    } catch (cause) {
      setError(cause.message);
      setState("ready");
    }
  }

  return <main className="invite-page"><section className="invite-card" aria-labelledby="transfer-title">
    <p className="invite-eyebrow">UH케그려 계정 관리</p>
    <h1 id="transfer-title">Google 계정 변경</h1>
    {state === "loading" && <p role="status">검증된 Google 계정을 확인하고 있습니다.</p>}
    {details && <dl><dt>현재 계정</dt><dd>{details.source_display_name || details.source_email} ({details.source_email})</dd><dt>변경할 Google 계정</dt><dd>{details.target_display_name || details.target_email} ({details.target_email})</dd></dl>}
    {state === "ready" && <><p>요청 후 관리자가 승인하면 기존 데이터와 누적 사용량은 유지되고 이전 로그인 세션은 종료됩니다.</p><button type="button" onClick={requestTransfer}>관리자에게 이전 요청</button></>}
    {state === "submitting" && <p role="status">이전 요청을 등록하고 있습니다.</p>}
    {state === "pending" && <p role="status">이전 요청을 등록했습니다. 관리자 승인 후 새 Google 계정으로 다시 로그인해 주세요.</p>}
    {error && <p className="invite-error" role="alert">{error}</p>}
    <a className="invite-link" href="/">돌아가기</a>
  </section></main>;
}
