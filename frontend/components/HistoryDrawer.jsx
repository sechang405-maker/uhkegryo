import { useLayoutEffect, useRef } from "react";

export function HistoryLogo({ open, onClick, className = "" }) {
  return <button className={`brand-identity history-logo ${className}`} type="button"
    aria-label={`UH케그려 기록 ${open ? "닫기" : "열기"}`} aria-expanded={open}
    aria-controls="history-sidebar" aria-haspopup="dialog" onClick={onClick}>
    <span className="brand-mark" aria-hidden="true">
      <svg className="brand-mark-art" viewBox="0 0 40 40" aria-hidden="true" focusable="false">
        <path className="brand-mark-frame" d="M15 4H9a5 5 0 0 0-5 5v6M4 25v6a5 5 0 0 0 5 5h6M25 36h6a5 5 0 0 0 5-5v-6" />
        <path className="brand-mark-monogram" fillRule="evenodd" d="M10 9h12l9 9v9a5 5 0 0 1-5 5H10a5 5 0 0 1-5-5V14a5 5 0 0 1 5-5Zm1.5 5h3v7.1c0 1.6.8 2.5 2.1 2.5s2.1-.9 2.1-2.5V14h3v7.1c0 3.4-1.9 5.3-5.1 5.3s-5.1-1.9-5.1-5.3V14Zm11.6 0h3v4.1h2.5V14h3v12.4h-3v-5.2h-2.5v5.2h-3V14Z" />
        <path className="brand-mark-pencil" d="m24 16 1.5-5.5 8-8 4 4-8 8-5.5 1.5Z" />
      </svg>
    </span>
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
