"use client";

import { useEffect, useState } from "react";

export default function InvitePage() {
  const [state, setState] = useState("loading");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    fetch("/api/auth/me", { credentials: "include" })
      .then(async (response) => response.ok ? response.json() : { state: "unavailable" })
      .then((body) => {
        if (!active) return;
        if (body.state === "authenticated") window.location.replace("/");
        else setState(body.state);
      })
      .catch(() => active && setState("unavailable"));
    return () => { active = false; };
  }, []);

  async function redeem(event) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch("/api/auth/invite/redeem", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json", "x-auth-action": "redeem" },
        body: JSON.stringify({ code: code.trim() }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "초대 코드를 확인하지 못했습니다.");
      }
      window.location.replace("/");
    } catch (caught) {
      setError(caught.message || "초대 코드를 확인하지 못했습니다.");
      setSubmitting(false);
    }
  }

  return (
    <main className="invite-page">
      <section className="invite-card" aria-labelledby="invite-title">
        <p className="invite-eyebrow">UH케그려 초대 데모</p>
        <h1 id="invite-title">초대 코드 등록</h1>
        {state === "loading" && <p role="status">로그인 상태를 확인하고 있습니다.</p>}
        {state === "invite_required" && (
          <form onSubmit={redeem}>
            <p>운영자에게 받은 개인 초대 코드를 한 번만 등록해 주세요.</p>
            <label htmlFor="invite-code">초대 코드</label>
            <input
              id="invite-code"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              minLength={20}
              maxLength={200}
              required
            />
            {error && <p className="invite-error" role="alert">{error}</p>}
            <button type="submit" disabled={submitting}>
              {submitting ? "등록 중…" : "등록하고 시작하기"}
            </button>
          </form>
        )}
        {state === "anonymous" && (
          <>
            <p>먼저 Google 로그인을 완료해 주세요.</p>
            <a className="invite-link" href="/api/auth/google/start">Google로 로그인</a>
          </>
        )}
        {state === "unavailable" && (
          <p role="alert">초대 로그인이 아직 활성화되지 않았거나 서버에 연결할 수 없습니다.</p>
        )}
      </section>
    </main>
  );
}
