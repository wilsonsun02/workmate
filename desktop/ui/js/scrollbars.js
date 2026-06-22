const DEFAULT_HIDE_DELAY_MS = 800;
const MIN_THUMB_PX = 36;
const THUMB_INSET_PX = 3;

/** @type {WeakMap<Element, { thumb: HTMLDivElement, hideTimer: number, visible: boolean }>} */
const thumbStates = new WeakMap();

/** @type {HTMLDivElement | null} */
let overlayRoot = null;

function isVerticallyScrollable(el) {
  if (!(el instanceof Element)) return false;
  const style = window.getComputedStyle(el);
  const overflowY = style.overflowY;
  return (
    (overflowY === "auto" || overflowY === "scroll") &&
    el.scrollHeight > el.clientHeight
  );
}

function ensureOverlayRoot() {
  if (overlayRoot && overlayRoot.isConnected) return overlayRoot;
  overlayRoot = document.createElement("div");
  overlayRoot.id = "wm-scroll-overlay";
  overlayRoot.setAttribute("aria-hidden", "true");
  document.body.appendChild(overlayRoot);
  return overlayRoot;
}

function getOrCreateState(el) {
  let state = thumbStates.get(el);
  if (state) return state;

  const thumb = document.createElement("div");
  thumb.className = "wm-scroll-thumb";
  ensureOverlayRoot().appendChild(thumb);

  state = { thumb, hideTimer: 0, visible: false };
  thumbStates.set(el, state);
  return state;
}

function syncVerticalThumb(el, thumb) {
  const rect = el.getBoundingClientRect();
  const clientHeight = el.clientHeight;
  const scrollHeight = el.scrollHeight;

  if (
    rect.width <= 0 ||
    rect.height <= 0 ||
    scrollHeight <= clientHeight
  ) {
    thumb.style.display = "none";
    return;
  }

  const thumbHeight = Math.max(
    MIN_THUMB_PX,
    (clientHeight / scrollHeight) * clientHeight
  );
  const maxScroll = scrollHeight - clientHeight;
  const scrollRatio = maxScroll > 0 ? el.scrollTop / maxScroll : 0;
  const thumbTravel = clientHeight - thumbHeight;
  const thumbTop = rect.top + scrollRatio * thumbTravel;
  const size =
    parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue(
        "--scrollbar-size"
      )
    ) || 10;

  thumb.style.display = "block";
  thumb.style.width = size + "px";
  thumb.style.height = thumbHeight + "px";
  thumb.style.left = rect.right - size - THUMB_INSET_PX + "px";
  thumb.style.top = thumbTop + "px";
}

function revealScrollbar(el, hideDelayMs) {
  if (!isVerticallyScrollable(el)) return;

  const state = getOrCreateState(el);
  syncVerticalThumb(el, state.thumb);

  if (state.hideTimer) window.clearTimeout(state.hideTimer);

  if (!state.visible) {
    state.thumb.classList.remove("is-visible");
    window.requestAnimationFrame(() => {
      state.thumb.classList.add("is-visible");
    });
    state.visible = true;
  }

  state.hideTimer = window.setTimeout(() => {
    state.thumb.classList.remove("is-visible");
    state.visible = false;
    state.hideTimer = 0;
  }, hideDelayMs);
}

function findScrollableAncestor(start) {
  let node = start;
  while (node instanceof Element) {
    if (isVerticallyScrollable(node)) return node;
    node = node.parentElement;
  }
  return null;
}

function bindScrollReveal(event, hideDelayMs) {
  const target = event.target;
  if (target instanceof Element && isVerticallyScrollable(target)) {
    revealScrollbar(target, hideDelayMs);
    return;
  }
  const scrollHost = findScrollableAncestor(target);
  if (scrollHost) revealScrollbar(scrollHost, hideDelayMs);
}

export function initAutoHideScrollbars(options = {}) {
  const hideDelayMs =
    typeof options.hideDelayMs === "number"
      ? options.hideDelayMs
      : DEFAULT_HIDE_DELAY_MS;

  ensureOverlayRoot();

  document.addEventListener(
    "scroll",
    (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (!isVerticallyScrollable(target)) return;
      revealScrollbar(target, hideDelayMs);
      const state = thumbStates.get(target);
      if (state) syncVerticalThumb(target, state.thumb);
    },
    { capture: true, passive: true }
  );

  document.addEventListener(
    "wheel",
    (event) => {
      bindScrollReveal(event, hideDelayMs);
    },
    { capture: true, passive: true }
  );

  document.addEventListener(
    "touchmove",
    (event) => {
      bindScrollReveal(event, hideDelayMs);
    },
    { capture: true, passive: true }
  );

  window.addEventListener(
    "resize",
    () => {
      thumbStates.forEach((state, el) => {
        if (!state.visible) return;
        syncVerticalThumb(el, state.thumb);
      });
    },
    { passive: true }
  );
}
