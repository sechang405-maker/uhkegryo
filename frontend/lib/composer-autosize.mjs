// Keep the input bounded without moving readers who are browsing older answers.
export function createScrollEndAnchor(container) {
  let followEnd = container.scrollHeight - container.clientHeight - container.scrollTop < 2;
  return {
    onScroll() { followEnd = container.scrollHeight - container.clientHeight - container.scrollTop < 2; },
    onResize() { if (followEnd) container.scrollTop = container.scrollHeight - container.clientHeight; },
  };
}

export function resizeComposerInput(input, { viewportHeight, scrollContainer } = {}) {
  if (!input?.offsetWidth) return;
  const atEnd = scrollContainer && scrollContainer.scrollHeight - scrollContainer.clientHeight - scrollContainer.scrollTop < 2;
  const inputTop = input.scrollTop;
  const inputAtEnd = input.scrollHeight - input.clientHeight - inputTop < 2;
  const maximum = Math.max(44, Math.min(164, Math.floor((viewportHeight || 656) * .25)));
  input.style.maxHeight = `${maximum}px`;
  input.style.height = 'auto';
  const needed = input.value ? Math.max(44, input.scrollHeight) : 44;
  input.style.height = `${Math.min(needed, maximum)}px`;
  input.style.overflowY = needed > maximum ? 'auto' : 'hidden';
  input.scrollTop = inputAtEnd ? input.scrollHeight : inputTop;
  if (atEnd) scrollContainer.scrollTop = scrollContainer.scrollHeight - scrollContainer.clientHeight;
}
