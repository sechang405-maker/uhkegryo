export function createAccountQuotaDisclosureState() {
  return false;
}

export function reduceAccountQuotaDisclosure(expanded, action) {
  if (action?.type === "toggle") return !expanded;
  if (["dismiss", "refresh", "navigate"].includes(action?.type)) return false;
  return expanded;
}

export function bindAccountQuotaDismissal({ documentTarget, windowTarget, root, onDismiss }) {
  const onPointerDown = (event) => {
    if (!root?.contains(event.target)) onDismiss();
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") onDismiss();
  };
  const onPageHide = () => onDismiss();

  documentTarget.addEventListener("pointerdown", onPointerDown);
  documentTarget.addEventListener("keydown", onKeyDown);
  windowTarget.addEventListener("pagehide", onPageHide);
  return () => {
    documentTarget.removeEventListener("pointerdown", onPointerDown);
    documentTarget.removeEventListener("keydown", onKeyDown);
    windowTarget.removeEventListener("pagehide", onPageHide);
  };
}
