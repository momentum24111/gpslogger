/**
 * Globaler Ink-Ripple (Material-ähnlich): currentColor, Dauer ab Entfernung zur Ecke.
 */

const RIPPLE_TARGET_SELECTOR = [
  "button",
  "[role='button']",
  ".ui-clickable",
  ".ui-tab",
  ".ui-nav-btn",
  "[role='menuitem']",
  "[role='tab']",
].join(", ");

const DURATION_MIN = 260;
const DURATION_MAX = 620;
const DURATION_PER_PX = 1.35;

function findRippleTarget(node) {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return null;
  return node.closest(RIPPLE_TARGET_SELECTOR);
}

function isRippleDisabled(el) {
  if (!(el instanceof HTMLElement)) return true;
  if (el.getAttribute("data-ripple") === "off") return true;
  if (el.classList.contains("toast-close")) return true;
  try {
    if (el.matches(":disabled")) return true;
  } catch (_e) {
    /* ignore */
  }
  if (el.getAttribute("aria-disabled") === "true") return true;
  if (el.classList.contains("disabled")) return true;
  return false;
}

function maxCornerDistance(localX, localY, w, h) {
  const corners = [
    [0, 0],
    [w, 0],
    [0, h],
    [w, h],
  ];
  let max = 0;
  for (const [cx, cy] of corners) {
    const d = Math.hypot(localX - cx, localY - cy);
    if (d > max) max = d;
  }
  return max;
}

function rippleDurationMs(maxDistance) {
  return Math.min(DURATION_MAX, Math.max(DURATION_MIN, Math.round(maxDistance * DURATION_PER_PX)));
}

function ensureRippleHost(el) {
  el.classList.add("ui-ripple-host");
  if (typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches) {
    el.classList.add("ui-ripple-host--coarse");
  }
}

function spawnRipple(target, localX, localY) {
  ensureRippleHost(target);
  const w = target.clientWidth;
  const h = target.clientHeight;
  const maxD = maxCornerDistance(localX, localY, w, h);
  const diameter = maxD * 2;
  const durationMs = rippleDurationMs(maxD);

  const wave = document.createElement("span");
  wave.className = "ui-ripple-wave";
  wave.setAttribute("aria-hidden", "true");
  wave.style.setProperty("--ripple-duration", `${durationMs}ms`);
  wave.style.left = `${localX}px`;
  wave.style.top = `${localY}px`;
  wave.style.width = `${diameter}px`;
  wave.style.height = `${diameter}px`;

  target.prepend(wave);

  const onEnd = () => {
    wave.removeEventListener("animationend", onEnd);
    wave.remove();
  };
  wave.addEventListener("animationend", onEnd);
}

function onPointerDown(e) {
  if (e.button !== 0) return;
  const target = findRippleTarget(e.target);
  if (!target) return;
  if (isRippleDisabled(target)) return;
  const rect = target.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  spawnRipple(target, x, y);
}

function onKeyDown(e) {
  if (e.repeat) return;
  if (e.key !== "Enter" && e.key !== " ") return;
  const active = document.activeElement;
  if (!active || !(active instanceof Element)) return;
  const target = findRippleTarget(active);
  if (!target) return;
  if (!target.contains(active)) return;
  if (isRippleDisabled(target)) return;
  const w = target.clientWidth;
  const h = target.clientHeight;
  spawnRipple(target, w / 2, h / 2);
}

export function initInkRipple() {
  const opts = { capture: true };
  document.addEventListener("pointerdown", onPointerDown, opts);
  document.addEventListener("keydown", onKeyDown, opts);
}
