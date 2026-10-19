import { useLayoutEffect, useRef } from "react";

export function HistoryLogo({ open, onClick, className = "" }) {
  return <button className={`brand-identity history-logo ${className}`} type="button"
    aria-label={`UH케그려 기록 ${open ? "닫기" : "열기"}`} aria-expanded={open}
    aria-controls="history-sidebar" aria-haspopup="dialog" onClick={onClick}>
    <span className="brand-mark" aria-hidden="true">UH</span>
    <span className="brand-name">UH케그려</span>
  </button>;
}

export default function HistoryDrawer({ open, onClose, triggerRef, children }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useLayoutEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = "hidden";
    dialog.querySelector("button")?.focus();
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      triggerRef.current?.focus();
    };
  }, [open, triggerRef]);

  function trapFocus(event) {
    if (event.key !== "Tab") return;
    const buttons = [...dialogRef.current.querySelectorAll("button:not(:disabled), a[href], [tabindex='0']")]
      .filter(element => element.getClientRects().length);
    const first = buttons[0], last = buttons.at(-1);
    if (!buttons.includes(document.activeElement)) {
      event.preventDefault(); first?.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  }

  const outsideDown = useRef(false);
  function outside(event) {
    const rect = dialogRef.current.getBoundingClientRect();
    return event.target === dialogRef.current &&
      (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom);
  }
  return <dialog id="history-sidebar" ref={dialogRef} className="history-drawer" aria-label="대화 기록"
    onCancel={event => { event.preventDefault(); closeRef.current(); }}
    onKeyDown={trapFocus} onPointerDown={event => { outsideDown.current = outside(event); }}
    onClick={event => { if (outsideDown.current && outside(event)) closeRef.current(); }}>
    <header className="history-drawer-header">
      <HistoryLogo open onClick={onClose} />
      <button type="button" className="history-close" aria-label="기록 닫기" onClick={onClose}>×</button>
    </header>
    {children}
  </dialog>;
}
