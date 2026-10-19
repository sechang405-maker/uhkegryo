"use client";
import { useEffect, useState } from 'react';
import { originalPinLink, pinUnavailableMessage } from '../lib/result-view.mjs';

export default function PinFailure({pin, disabled, onReload}) {
  const [remaining, setRemaining] = useState(() => Math.ceil(pin.retry_after_seconds || 0));
  useEffect(() => {
    const deadline = Date.now() + (pin.retry_after_seconds || 0) * 1000;
    setRemaining(Math.ceil(pin.retry_after_seconds || 0));
    if (!pin.retry_after_seconds) return;
    const timer = setInterval(() => setRemaining(Math.max(0, Math.ceil((deadline - Date.now()) / 1000))), 1000);
    return () => clearInterval(timer);
  }, [pin.retry_after_seconds]);
  const link = originalPinLink(pin);
  return <div className="pin-gallery-card pin-unavailable">
    <p>{pinUnavailableMessage(pin)}</p>
    {pin.status !== 'deleted' && pin.failure_reason !== 'access_restricted' &&
      <button type="button" disabled={disabled || remaining > 0} onClick={onReload}>
        {remaining > 0 ? `${remaining}초 후 다시 불러오기` : '미리보기 다시 불러오기'}
      </button>}
    {link && <a href={link} target="_blank" rel="noopener noreferrer">Pinterest 원문 보기</a>}
  </div>;
}
