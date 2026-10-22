import { useLayoutEffect, useRef } from "react";

export function HistoryLogo({ open, onClick, className = "" }) {
  return <button className={`brand-identity history-logo ${className}`} type="button"
    aria-label={`UH케그려 기록 ${open ? "닫기" : "열기"}`} aria-expanded={open}
    aria-controls="history-sidebar" aria-haspopup="dialog" onClick={onClick}>
    <span className="brand-mark" aria-hidden="true">
      <svg className="brand-mark-art" viewBox="0 0 34 34" aria-hidden="true" focusable="false">
        <path fill="currentColor" fillRule="evenodd" d="M12 0h10c6.627 0 12 5.373 12 12v10c0 6.627-5.373 12-12 12H12C5.373 34 0 28.627 0 22V12C0 5.373 5.373 0 12 0Zm-4 9h3v10c0 2.2 1.2 3.5 3 3.5s3-1.3 3-3.5V9h3v10c0 4.2-2.4 6.5-6 6.5S8 23.2 8 19V9Zm14 0h3v6h3V9h3v16h-3v-7h-3v7h-3V9Z" />
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
