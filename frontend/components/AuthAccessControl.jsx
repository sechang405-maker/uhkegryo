"use client";

import { useEffect, useState } from "react";
import {
  AUTH_STATE_EVENT,
  createAuthStateTracker,
  readAuthState,
} from "../lib/auth-state.mjs";

export default function AuthAccessControl() {
  const [auth, setAuth] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    let generation = 0;
    const trackAuthState = createAuthStateTracker(() => {
      window.dispatchEvent(new Event(AUTH_STATE_EVENT));
    });

    function refresh() {
      const current = ++generation;
      readAuthState()
        .then((next) => {
          if (!active || current !== generation || next === null) return;
          if (next.state === "invite_required") {
            window.location.replace("/invite");
            return;
          }
          trackAuthState(next);
          setAuth(next);
        })
        .catch(() => {
          if (active && current === generation) setAuth({ state: "unavailable" });
        });
    }

    const onPageShow = () => refresh();
    const onFocus = () => refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    refresh();
    window.addEventListener("pageshow", onPageShow);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      generation += 1;
      window.removeEventListener("pageshow", onPageShow);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  async function logout() {
    if (busy) return;
    setBusy(true);
    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
        headers: { "x-auth-action": "logout" },
      });
      if (!response.ok) throw new Error("logout failed");
      window.location.replace("/invite");
    } catch {
      setBusy(false);
      setAuth({ state: "unavailable" });
    }
  }

  if (!auth) return null;
  if (auth.state === "anonymous") {
    return <a className="auth-access-control" href="/api/auth/google/start">Google로 로그인</a>;
  }
  if (auth.state === "authenticated") {
    return (
      <button className="auth-access-control" type="button" disabled={busy} onClick={logout}>
        {busy ? "로그아웃 중…" : "로그아웃"}
      </button>
    );
  }
  if (auth.state === "unavailable") {
    return <span className="auth-access-error" role="status">로그인 상태를 확인할 수 없습니다.</span>;
  }
  return null;
}
