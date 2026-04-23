export function createButton({ label, icon, onClick, selected = false, disabled = false }) {
  const btn = document.createElement("button");
  btn.className = "btn";
  btn.type = "button";
  if (selected) btn.classList.add("selected");
  btn.disabled = disabled;
  if (icon) {
    btn.innerHTML = `<span class="material-symbols-outlined">${icon}</span> ${label}`;
  } else {
    btn.textContent = label;
  }
  btn.addEventListener("click", () => onClick?.());
  return btn;
}

export function createIconButton({ icon, title, onClick }) {
  const btn = document.createElement("button");
  btn.className = "icon-btn";
  btn.title = title ?? "";
  btn.innerHTML = `<span class="material-symbols-outlined">${icon}</span>`;
  btn.addEventListener("click", () => onClick?.());
  return btn;
}

export function createSwitch({ label, value, onChange }) {
  const wrap = document.createElement("div");
  wrap.className = "switch";
  const btn = document.createElement("button");
  btn.type = "button";
  if (value) btn.classList.add("enabled");
  btn.addEventListener("click", () => {
    const next = !btn.classList.contains("enabled");
    btn.classList.toggle("enabled", next);
    onChange?.(next);
  });
  if (label) {
    const text = document.createElement("span");
    text.textContent = label;
    wrap.append(text, btn);
  } else {
    wrap.append(btn);
  }
  return { wrap, toggle: btn };
}

export function createField({ label, type = "text", value = "", placeholder = "" }) {
  const field = document.createElement("label");
  field.className = "field";
  const text = document.createElement("span");
  text.textContent = label;
  const message = document.createElement("small");
  message.className = "field-message";
  let input;
  if (type === "textarea") {
    input = document.createElement("textarea");
    input.className = "textarea";
  } else if (type === "select") {
    input = document.createElement("select");
    input.className = "select";
  } else {
    input = document.createElement("input");
    input.className = "input";
    input.type = type;
  }
  input.value = value;
  input.placeholder = placeholder;
  field.append(text, input, message);
  return { field, input, message };
}

export function setFieldState(fieldObj, state = "default", message = "") {
  if (!fieldObj?.field || !fieldObj?.message) return;
  fieldObj.field.classList.remove("is-error", "is-success");
  if (state === "error") fieldObj.field.classList.add("is-error");
  if (state === "success") fieldObj.field.classList.add("is-success");
  fieldObj.message.textContent = message;
}

export function createToastArea() {
  const area = document.createElement("div");
  area.className = "toast-area";
  area.dataset.toastInitialized = "0";
  area.dataset.toastCounter = "0";
  return area;
}

const TOAST_MAX_VISIBLE = 4;
const TOAST_DEFAULT_DURATION_MS = 4200;
const TOAST_LEAVE_DURATION_MS = 260;
const TOAST_VARIANTS = {
  success: {
    icon: "check_circle",
    title: "Erfolg",
  },
  error: {
    icon: "error",
    title: "Fehler",
  },
  info: {
    icon: "info",
    title: "Hinweis",
  },
};

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function getToastState(area) {
  if (!area.__toastState) {
    area.__toastState = {
      queue: [],
      visible: new Map(),
      initialized: false,
    };
  }
  return area.__toastState;
}

function normalizeToastInput(inputOrText, level) {
  if (typeof inputOrText === "string") {
    return {
      level: level || "success",
      title: "",
      description: inputOrText,
      durationMs: TOAST_DEFAULT_DURATION_MS,
      icon: "",
    };
  }
  const input = inputOrText && typeof inputOrText === "object" ? inputOrText : {};
  return {
    level: input.level || level || "success",
    title: String(input.title || "").trim(),
    description: String(input.description || input.text || "").trim(),
    durationMs: Number.isFinite(Number(input.durationMs)) ? Math.max(1200, Number(input.durationMs)) : TOAST_DEFAULT_DURATION_MS,
    icon: String(input.icon || "").trim(),
  };
}

function createToastElement(toast) {
  const variant = TOAST_VARIANTS[toast.level] || TOAST_VARIANTS.info;
  const item = document.createElement("article");
  item.className = `toast toast--${toast.level}`;
  item.setAttribute("role", toast.level === "error" ? "alert" : "status");
  const iconName = toast.icon || variant.icon;
  const titleText = toast.title || variant.title;
  item.innerHTML = `
    <div class="toast-icon" aria-hidden="true"><span class="material-symbols-outlined">${escapeHtml(iconName)}</span></div>
    <div class="toast-content">
      <div class="toast-title">${escapeHtml(titleText)}</div>
      <div class="toast-description">${escapeHtml(toast.description)}</div>
    </div>
    <button class="toast-close icon-btn" type="button" aria-label="Toast schließen">
      <span class="material-symbols-outlined" aria-hidden="true">close</span>
    </button>
  `;
  return item;
}

function removeToast(area, id) {
  const state = getToastState(area);
  const entry = state.visible.get(id);
  if (!entry || entry.leaving) return;
  entry.leaving = true;
  if (entry.timer) {
    clearTimeout(entry.timer);
    entry.timer = null;
  }
  entry.el.classList.add("is-leaving");
  window.setTimeout(() => {
    entry.el.remove();
    state.visible.delete(id);
    drainToastQueue(area);
  }, TOAST_LEAVE_DURATION_MS);
}

function drainToastQueue(area) {
  const state = getToastState(area);
  while (state.visible.size < TOAST_MAX_VISIBLE && state.queue.length > 0) {
    const next = state.queue.shift();
    const id = String(Number(area.dataset.toastCounter || "0") + 1);
    area.dataset.toastCounter = id;
    const el = createToastElement(next);
    const closeBtn = el.querySelector(".toast-close");
    const entry = {
      id,
      el,
      timer: null,
      leaving: false,
    };
    state.visible.set(id, entry);
    closeBtn?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removeToast(area, id);
    });
    area.appendChild(el);
    requestAnimationFrame(() => el.classList.add("is-visible"));
    entry.timer = window.setTimeout(() => removeToast(area, id), next.durationMs);
  }
}

export function pushToast(area, inputOrText, level = "success") {
  if (!area) return;
  const state = getToastState(area);
  if (!state.initialized) {
    area.dataset.toastInitialized = "1";
    state.initialized = true;
  }
  const normalized = normalizeToastInput(inputOrText, level);
  if (!normalized.description) return;
  state.queue.push(normalized);
  drainToastQueue(area);
}

export function setButtonLoading(button, isLoading, loadingLabel = "Lädt...") {
  if (!button) return;
  if (isLoading) {
    if (!button.dataset.originalHtml) {
      button.dataset.originalHtml = button.innerHTML;
    }
    button.disabled = true;
    button.classList.add("loading");
    button.textContent = loadingLabel;
    return;
  }
  button.disabled = false;
  button.classList.remove("loading");
  if (button.dataset.originalHtml) {
    button.innerHTML = button.dataset.originalHtml;
    delete button.dataset.originalHtml;
  }
}

export function readModalAnimationDurationMs() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--modal-animation-duration").trim() || "240ms";
  const v = parseFloat(raw);
  if (!Number.isFinite(v)) return 280;
  return /ms/i.test(raw) ? v : v * 1000;
}

function removeModalOverlay(overlay) {
  overlay.remove();
}

export function createModal({
  title,
  content,
  actions = [],
  closeOnEscape = true,
  closeOnBackdrop = true,
  routeHash = "",
  clearExistingHashOnOpen = false,
}) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  const modal = document.createElement("div");
  modal.className = "modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");

  const head = document.createElement("div");
  head.className = "modal-head";
  head.innerHTML = `<h3>${title}</h3>`;

  const body = document.createElement("div");
  body.className = "modal-body";
  if (typeof content === "string") {
    body.innerHTML = content;
  } else if (content instanceof Node) {
    body.appendChild(content);
  }

  const foot = document.createElement("div");
  foot.className = "modal-actions";
  actions.forEach((btn) => foot.appendChild(btn));

  modal.append(head, body, foot);
  overlay.appendChild(modal);
  let keyListener = null;
  let backdropListener = null;
  let backdropPointerDown = null;
  let hashListener = null;
  let routeManaged = false;
  let closing = false;

  const removeCurrentHash = () => {
    history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  };

  const setupRouteHash = (self) => {
    if (!routeHash) return;
    if (clearExistingHashOnOpen && window.location.hash && window.location.hash !== routeHash) {
      removeCurrentHash();
    }
    if (window.location.hash !== routeHash) {
      window.location.hash = routeHash;
    }
    routeManaged = true;
    hashListener = () => {
      if (window.location.hash === routeHash || closing) return;
      self.close({ skipRouteCleanup: true });
    };
    window.addEventListener("hashchange", hashListener);
  };

  const armCloseListeners = (self) => {
    if (closeOnBackdrop) {
      backdropPointerDown = (event) => {
        if (closing) return;
        overlay.dataset.pointerDownOnOverlay = event.target === overlay ? "1" : "0";
      };
      backdropListener = (event) => {
        if (event.target !== overlay || closing) return;
        if (overlay.dataset.pointerDownOnOverlay !== "1") return;
        self.close();
      };
      overlay.addEventListener("pointerdown", backdropPointerDown);
      overlay.addEventListener("click", backdropListener);
    }
    if (closeOnEscape) {
      keyListener = (event) => {
        if (event.key === "Escape" && !closing) {
          self.close();
        }
      };
      document.addEventListener("keydown", keyListener);
    }
  };

  return {
    overlay,
    open() {
      document.body.appendChild(overlay);
      setupRouteHash(this);
      armCloseListeners(this);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          overlay.classList.add("modal-overlay--shown");
        });
      });
      const focusTarget = actions[0] ?? modal;
      setTimeout(() => focusTarget.focus?.(), 0);
    },
    close({ skipRouteCleanup = false } = {}) {
      if (!overlay.parentNode || closing) return;
      closing = true;
      if (hashListener) {
        window.removeEventListener("hashchange", hashListener);
        hashListener = null;
      }
      if (backdropListener) {
        overlay.removeEventListener("click", backdropListener);
        backdropListener = null;
      }
      if (backdropPointerDown) {
        overlay.removeEventListener("pointerdown", backdropPointerDown);
        backdropPointerDown = null;
      }
      if (keyListener) {
        document.removeEventListener("keydown", keyListener);
        keyListener = null;
      }
      if (!skipRouteCleanup && routeManaged && routeHash) {
        if (window.location.hash === routeHash) {
          if (window.history.length > 1) {
            history.back();
          } else {
            removeCurrentHash();
          }
        }
      }
      overlay.classList.remove("modal-overlay--shown");
      const ms = readModalAnimationDurationMs() + 40;
      window.setTimeout(() => removeModalOverlay(overlay), ms);
    },
  };
}

export function openInfoModal({ title, content, closeLabel = "Schließen" }) {
  const closeBtn = createButton({ label: closeLabel });
  const modal = createModal({ title, content, actions: [closeBtn] });
  closeBtn.addEventListener("click", () => modal.close());
  modal.open();
  return modal;
}

export function openConfirmModal({ title, message, confirmLabel = "Bestätigen", cancelLabel = "Abbrechen", onConfirm }) {
  const content = document.createElement("div");
  content.textContent = message;
  const cancelBtn = createButton({ label: cancelLabel });
  const confirmBtn = createButton({
    label: confirmLabel,
    onClick: async () => {
      setButtonLoading(confirmBtn, true, "Bitte warten...");
      try {
        await onConfirm?.();
        modal.close();
      } catch (_err) {
        // Fehlerhandling erfolgt beim aufrufenden Code.
      } finally {
        setButtonLoading(confirmBtn, false);
      }
    },
  });
  const modal = createModal({ title, content, actions: [cancelBtn, confirmBtn] });
  cancelBtn.addEventListener("click", () => modal.close());
  modal.open();
  return modal;
}

export function openFormModal({
  title,
  fields,
  submitLabel = "Speichern",
  cancelLabel = "Abbrechen",
  onSubmit,
}) {
  const content = document.createElement("div");
  const controls = {};
  const fieldMap = {};
  fields.forEach((entry) => {
    const built = createField(entry);
    controls[entry.key] = built.input;
    fieldMap[entry.key] = built;
    content.appendChild(built.field);
  });
  const cancelBtn = createButton({ label: cancelLabel });
  const submitBtn = createButton({
    label: submitLabel,
    onClick: async () => {
      const values = {};
      Object.entries(controls).forEach(([key, input]) => {
        values[key] = input.value;
      });
      setButtonLoading(submitBtn, true, "Bitte warten...");
      try {
        await onSubmit?.(values, controls, fieldMap);
        modal.close();
      } catch (_err) {
        // Fehlerhandling erfolgt beim aufrufenden Code.
      } finally {
        setButtonLoading(submitBtn, false);
      }
    },
  });
  const modal = createModal({ title, content, actions: [cancelBtn, submitBtn] });
  cancelBtn.addEventListener("click", () => modal.close());
  modal.open();
  return { modal, controls, fieldMap };
}
