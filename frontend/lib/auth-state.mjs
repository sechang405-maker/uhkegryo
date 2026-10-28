export const AUTH_STATE_EVENT = "uhkegryo-auth-state-change";

export async function readAuthState(options = {}) {
  const response = await (options.fetchImpl || globalThis.fetch)("/api/auth/me", {
    credentials: "include", cache: "no-store", signal: options.signal,
  });
  if (response.status === 404) return null;
  if (response.status === 401) return { state: "anonymous" };
  if (!response.ok) throw new Error("auth unavailable");
  return response.json();
}

function identityKey(auth) {
  return JSON.stringify([auth?.state || null, auth?.account_id || null, auth?.role || null]);
}

export function createAuthStateTracker(onChange) {
  let previous = null;
  return (next) => {
    const current = identityKey(next);
    const changed = previous !== null && previous !== current;
    previous = current;
    if (changed) onChange(next);
    return changed;
  };
}

export function bindAuthStateChange(target, onChange) {
  target.addEventListener(AUTH_STATE_EVENT, onChange);
  return () => target.removeEventListener(AUTH_STATE_EVENT, onChange);
}
