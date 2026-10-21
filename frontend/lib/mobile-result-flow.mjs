const KEYS = ["requestId", "sessionId", "screenGeneration", "panelRevision"];

export function createMobileResultOrigin(value) {
  return Object.freeze(Object.fromEntries(KEYS.map((key) => [key, value?.[key] ?? null])));
}

export function resolveMobileResult(origin, current) {
  const accepted = Boolean(origin) && KEYS.slice(0, 3).every((key) => origin[key] === (current?.[key] ?? null));
  return {
    accepted,
    shouldOpen: accepted && origin.panelRevision === (current?.panelRevision ?? null),
  };
}
