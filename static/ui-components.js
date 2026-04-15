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
  return area;
}

export function pushToast(area, text, level = "success") {
  const item = document.createElement("div");
  item.className = `toast ${level}`;
  item.textContent = text;
  area.appendChild(item);
  setTimeout(() => item.remove(), 2800);
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

export function createModal({ title, content, actions = [], closeOnEscape = true, closeOnBackdrop = true }) {
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
  let closing = false;

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
      armCloseListeners(this);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          overlay.classList.add("modal-overlay--shown");
        });
      });
      const focusTarget = actions[0] ?? modal;
      setTimeout(() => focusTarget.focus?.(), 0);
    },
    close() {
      if (!overlay.parentNode || closing) return;
      closing = true;
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
