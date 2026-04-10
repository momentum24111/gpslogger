import {
  createButton,
  createField,
  createModal,
  createSwitch,
  createToastArea,
  openConfirmModal,
  openFormModal,
  openInfoModal,
  pushToast,
  setFieldState,
  setButtonLoading,
} from "/static/ui-components.js";

const ui = {
  pages: {},
  toastArea: null,
  map: null,
  layers: {},
  markers: new Map(),
  routeLines: [],
  mapMode: localStorage.getItem("gpslogger.map.mode") || "satellite",
  showHistory: (localStorage.getItem("gpslogger.map.showHistory") || "true") === "true",
  activePage: "map",
  autoRefreshHandle: null,
  mapRange: localStorage.getItem("gpslogger.map.range") || "24h",
};

const state = {
  devices: [],
  deviceStatuses: {},
  settings: {},
  systemStatus: {},
  forwardingErrors: [],
  recentGps: [],
  themes: [],
  selectedDeviceId: localStorage.getItem("gpslogger.selectedDeviceId") || "",
};

const PAGE_IDS = new Set(["map", "settings"]);

function isHttpUrl(value) {
  if (!value) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch (_err) {
    return false;
  }
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "API Fehler");
  return data;
}

async function bootstrap() {
  ui.toastArea = createToastArea();
  document.body.appendChild(ui.toastArea);

  await Promise.all([loadDevices(), loadDeviceStatuses(), loadSettings(), loadThemes(), loadSystemStatus(), loadForwardingErrors()]);
  applyTheme(state.settings.theme || "light");
  buildTabs();
  buildMapPage();
  buildSettingsPage();
  initRouting();
  const brandHome = document.getElementById("brand-home");
  brandHome?.addEventListener("click", () => showPage("map"));
  await refreshMapData();
  startAutoRefresh();
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopAutoRefresh();
    } else {
      runAutoRefreshCycle();
      startAutoRefresh();
    }
  });
}

function normalizeHashPage() {
  const raw = window.location.hash.replace(/^#/, "").trim();
  return PAGE_IDS.has(raw) ? raw : "map";
}

function initRouting() {
  showPage(normalizeHashPage(), { updateHash: true });
  window.addEventListener("hashchange", () => {
    showPage(normalizeHashPage(), { updateHash: false });
  });
}

function buildTabs() {
  const tabs = document.getElementById("tabs");
  tabs.innerHTML = "";
  tabs.classList.add("ui-nav");
  [
    { id: "map", label: "Karte", icon: "map" },
    { id: "settings", label: "Einstellungen", icon: "settings" },
  ].forEach((tab) => {
    const host = document.createElement("div");
    host.className = "tab ui-tab";
    const btn = createButton({
      label: tab.label,
      icon: tab.icon,
      onClick: () => showPage(tab.id),
    });
    btn.classList.add("ui-nav-btn");
    btn.dataset.page = tab.id;
    host.appendChild(btn);
    tabs.appendChild(host);
  });
}

function showPage(pageId, { updateHash = true } = {}) {
  ui.activePage = pageId;
  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.id === `page-${pageId}`);
  });
  document.querySelectorAll("#tabs .btn").forEach((btn) => {
    btn.classList.toggle("selected", btn.dataset.page === pageId);
  });
  if (updateHash) {
    const target = `#${pageId}`;
    if (window.location.hash !== target) window.location.hash = target;
  }
  if (pageId === "map" && ui.map) {
    setTimeout(() => ui.map.invalidateSize(), 100);
  }
}

async function runAutoRefreshCycle() {
  try {
    if (ui.activePage === "map") {
      await refreshMapData();
    }
    if (ui.activePage === "settings") {
      await loadSettings();
      await loadDevices();
      await loadDeviceStatuses();
      await loadSystemStatus();
      await loadForwardingErrors();
      await loadRecentGps();
      renderForwardingList();
      renderDeviceList();
      renderSystemStatus();
      renderForwardingErrors();
      renderRecentGps();
    }
  } catch (_err) {
    // Hintergrund-Refresh bleibt bewusst still.
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  ui.autoRefreshHandle = setInterval(runAutoRefreshCycle, 15000);
}

function stopAutoRefresh() {
  if (ui.autoRefreshHandle) {
    clearInterval(ui.autoRefreshHandle);
    ui.autoRefreshHandle = null;
  }
}

function syncMapDeviceSelectOptions(selectElement) {
  if (!selectElement) return;
  const previous = state.selectedDeviceId;
  selectElement.innerHTML = `<option value="">Alle Geräte</option>${state.devices
    .map((d) => `<option value="${d.id}">${d.name}</option>`)
    .join("")}`;
  const stillExists = state.devices.some((d) => d.id === previous);
  state.selectedDeviceId = stillExists ? previous : "";
  selectElement.value = state.selectedDeviceId;
  localStorage.setItem("gpslogger.selectedDeviceId", state.selectedDeviceId);
}

function buildMapPage() {
  const page = document.getElementById("page-map");
  page.innerHTML = `<div class="map-layout"><div class="card ui-panel map-filters-panel"><div id="map-filters" class="ui-form-grid"></div><div id="map-actions" class="ui-actions-row"></div></div><div class="map-wrap ui-map-wrap"><div id="map"></div><div class="map-overlay ui-overlay-panel" id="map-overlay"></div></div></div>`;

  const filtersHost = page.querySelector("#map-filters");
  const deviceField = createField({ label: "Gerät", type: "select" });
  deviceField.input.id = "map-device";
  const rangeField = document.createElement("div");
  rangeField.className = "field";
  const rangeLabel = document.createElement("span");
  rangeLabel.textContent = "Zeitraum";
  const rangePicker = document.createElement("div");
  rangePicker.className = "segmented map-range-picker";
  const ranges = [
    { value: "1h", label: "Letzte Stunde" },
    { value: "6h", label: "Letzte 6 Stunden" },
    { value: "24h", label: "Letzte 24 Stunden" },
    { value: "7d", label: "Letzte Woche" },
    { value: "30d", label: "Letzte 30 Tage" },
    { value: "custom", label: "Custom" },
  ];
  ranges.forEach((entry) => {
    const id = `range-${entry.value}`;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "map-range";
    input.id = id;
    input.value = entry.value;
    input.checked = ui.mapRange === entry.value;
    const label = document.createElement("label");
    label.setAttribute("for", id);
    label.textContent = entry.label;
    input.addEventListener("change", () => {
      if (!input.checked) return;
      ui.mapRange = entry.value;
      localStorage.setItem("gpslogger.map.range", ui.mapRange);
      customDateWrap.hidden = ui.mapRange !== "custom";
      refreshMapData({ reloadBtn, fromField, toField });
    });
    rangePicker.append(input, label);
  });
  rangeField.append(rangeLabel, rangePicker);
  const customDateWrap = document.createElement("div");
  customDateWrap.className = "map-custom-dates";
  const fromField = createField({ label: "Von Datum", type: "date" });
  fromField.input.id = "map-from";
  fromField.input.value = localStorage.getItem("gpslogger.map.fromDate") || "";
  const toField = createField({ label: "Bis Datum", type: "date" });
  toField.input.id = "map-to";
  toField.input.value = localStorage.getItem("gpslogger.map.toDate") || "";
  customDateWrap.append(fromField.field, toField.field);
  customDateWrap.hidden = ui.mapRange !== "custom";
  filtersHost.append(deviceField.field, rangeField, customDateWrap);

  const actionHost = page.querySelector("#map-actions");
  const reloadBtn = createButton({
    label: "Route laden",
    icon: "route",
    onClick: () => refreshMapData({ fromField, toField, reloadBtn }),
  });
  reloadBtn.classList.add("btn-primary", "ui-primary-action");
  actionHost.appendChild(
    reloadBtn,
  );

  const mapDevice = deviceField.input;
  syncMapDeviceSelectOptions(mapDevice);
  mapDevice.addEventListener("change", () => {
    state.selectedDeviceId = mapDevice.value;
    localStorage.setItem("gpslogger.selectedDeviceId", state.selectedDeviceId);
    refreshMapData({ fromField, toField, reloadBtn });
  });
  fromField.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && ui.mapRange === "custom") {
      refreshMapData({ fromField, toField, reloadBtn });
    }
  });
  toField.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && ui.mapRange === "custom") {
      refreshMapData({ fromField, toField, reloadBtn });
    }
  });
  fromField.input.addEventListener("change", () => {
    localStorage.setItem("gpslogger.map.fromDate", fromField.input.value || "");
    if (ui.mapRange === "custom") refreshMapData({ fromField, toField, reloadBtn });
  });
  toField.input.addEventListener("change", () => {
    localStorage.setItem("gpslogger.map.toDate", toField.input.value || "");
    if (ui.mapRange === "custom") refreshMapData({ fromField, toField, reloadBtn });
  });

  ui.map = L.map("map", { zoomControl: true, scrollWheelZoom: true, touchZoom: true }).setView([51.2, 10.4], 6);
  ui.layers.street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
    maxZoom: 19,
  });
  ui.layers.satellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Tiles &copy; Esri", maxZoom: 19 },
  );
  if (ui.mapMode === "satellite") {
    ui.layers.satellite.addTo(ui.map);
  } else {
    ui.layers.street.addTo(ui.map);
  }

  const overlay = page.querySelector("#map-overlay");
  const historySwitch = createSwitch({
    label: "Historie",
    value: ui.showHistory,
    onChange: (enabled) => {
      ui.showHistory = enabled;
      localStorage.setItem("gpslogger.map.showHistory", String(enabled));
      ui.routeLines.forEach((line) => {
        if (enabled) {
          if (!ui.map.hasLayer(line)) line.addTo(ui.map);
        } else if (ui.map.hasLayer(line)) {
          ui.map.removeLayer(line);
        }
      });
    },
  });
  const layerSwitch = createSwitch({
    label: "Satellit",
    value: ui.mapMode === "satellite",
    onChange: (enabled) => setMapMode(enabled ? "satellite" : "street"),
  });
  historySwitch.wrap.classList.add("ui-map-toggle");
  layerSwitch.wrap.classList.add("ui-map-toggle");
  overlay.appendChild(historySwitch.wrap);
  overlay.appendChild(layerSwitch.wrap);
}

function setMapMode(mode) {
  if (ui.mapMode === mode) return;
  ui.map.removeLayer(ui.layers[ui.mapMode]);
  ui.map.addLayer(ui.layers[mode]);
  ui.mapMode = mode;
  localStorage.setItem("gpslogger.map.mode", mode);
}

async function refreshMapData(opts = {}) {
  const fromInput = document.getElementById("map-from");
  const toInput = document.getElementById("map-to");
  const { from, to, error } = resolveRangeQuery(
    ui.mapRange,
    fromInput?.value || "",
    toInput?.value || "",
  );
  if (fromInput) localStorage.setItem("gpslogger.map.fromDate", fromInput.value || "");
  if (toInput) localStorage.setItem("gpslogger.map.toDate", toInput.value || "");
  const fromField = opts.fromField || (fromInput ? { field: fromInput.closest(".field"), input: fromInput, message: fromInput.closest(".field")?.querySelector(".field-message") } : null);
  const toField = opts.toField || (toInput ? { field: toInput.closest(".field"), input: toInput, message: toInput.closest(".field")?.querySelector(".field-message") } : null);

  setFieldState(fromField, "default", "");
  setFieldState(toField, "default", "");
  if (error) {
    setFieldState(fromField, "error", error);
    setFieldState(toField, "error", error);
    return;
  }

  if (opts.reloadBtn) {
    setButtonLoading(opts.reloadBtn, true, "Lädt...");
  }
  const query = new URLSearchParams();
  if (state.selectedDeviceId) query.set("device_id", state.selectedDeviceId);
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  try {
    const data = await api(`/api/positions?${query.toString()}`);
    const positions = data.positions || [];
    setFieldState(fromField, "success", "");
    setFieldState(toField, "success", "");
    drawPositions(positions);
  } catch (err) {
    pushToast(ui.toastArea, err.message, "error");
  } finally {
    if (opts.reloadBtn) {
      setButtonLoading(opts.reloadBtn, false);
    }
  }
}

function resolveRangeQuery(range, customFrom, customTo) {
  const now = new Date();
  if (range === "custom") {
    if (!customFrom || !customTo) {
      return { from: "", to: "", error: "Bitte Von- und Bis-Datum setzen." };
    }
    const fromDate = new Date(`${customFrom}T00:00:00`);
    const toDate = new Date(`${customTo}T23:59:59.999`);
    if (Number.isNaN(fromDate.getTime()) || Number.isNaN(toDate.getTime())) {
      return { from: "", to: "", error: "Ungültiges Datum." };
    }
    if (fromDate.getTime() > toDate.getTime()) {
      return { from: "", to: "", error: "Von darf nicht nach Bis liegen." };
    }
    return { from: fromDate.toISOString(), to: toDate.toISOString(), error: "" };
  }
  const map = {
    "1h": 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
  };
  const delta = map[range] || map["24h"];
  const fromDate = new Date(now.getTime() - delta);
  return { from: fromDate.toISOString(), to: now.toISOString(), error: "" };
}

function drawPositions(positions) {
  ui.markers.forEach((marker) => ui.map.removeLayer(marker));
  ui.markers.clear();
  ui.routeLines.forEach((line) => ui.map.removeLayer(line));
  ui.routeLines = [];
  if (!positions.length) return;

  const byDevice = new Map();
  positions.forEach((p) => {
    if (!byDevice.has(p.device_id)) byDevice.set(p.device_id, []);
    byDevice.get(p.device_id).push(p);
  });

  const allLatLng = [];
  byDevice.forEach((items) => {
    items.sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
    const route = items.map((item) => [item.latitude, item.longitude]);
    allLatLng.push(...route);
    const line = L.polyline(route, { color: "var(--color-primary)" }).addTo(ui.map);
    if (!ui.showHistory) {
      ui.map.removeLayer(line);
    }
    ui.routeLines.push(line);
    const latest = items[items.length - 1];
    const icon = L.divIcon({ className: "", html: `<div class="pulse-marker"></div>`, iconSize: [20, 20] });
    const marker = L.marker([latest.latitude, latest.longitude], { icon }).addTo(ui.map);
    marker.bindPopup(`${latest.device_name}<br>${latest.timestamp}`);
    ui.markers.set(latest.device_id, marker);
  });

  const bounds = L.latLngBounds(allLatLng);
  if (bounds.isValid()) ui.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 18 });
}

function renderDevicesSection() {
  const createHost = document.getElementById("devices-create");
  const listHost = document.getElementById("devices-list");
  if (!createHost || !listHost) return;
  createHost.innerHTML = "";
  const addBtn = createButton({
    label: "Gerät hinzufügen",
    icon: "add",
    onClick: () => openAddDeviceModal(),
  });
  addBtn.classList.add("btn-primary");
  createHost.appendChild(addBtn);
  renderDeviceList();
}

async function openAddDeviceModal() {
  let draft;
  try {
    draft = await api("/api/devices/draft", { method: "POST", body: JSON.stringify({}) });
  } catch (err) {
    pushToast(ui.toastArea, err.message, "error");
    return;
  }
  const content = document.createElement("div");
  const nameField = createField({ label: "Name", placeholder: "z. B. Caspar" });
  const keyField = createField({ label: "API-Key (wird erst mit Speichern wirksam)", value: draft.api_key });
  keyField.input.readOnly = true;
  content.append(nameField.field, keyField.field);
  const cancelBtn = createButton({ label: "Abbrechen" });
  const saveBtn = createButton({ label: "Speichern", icon: "check" });
  saveBtn.classList.add("btn-primary");
  const modal = createModal({
    title: "Gerät hinzufügen",
    content,
    actions: [cancelBtn, saveBtn],
  });
  cancelBtn.addEventListener("click", () => modal.close());
  saveBtn.addEventListener("click", async () => {
    const name = nameField.input.value.trim();
    if (!name) {
      setFieldState(nameField, "error", "Bitte Namen eingeben.");
      return;
    }
    setFieldState(nameField, "default", "");
    setButtonLoading(saveBtn, true, "Speichert...");
    try {
      await api("/api/devices/commit", {
        method: "POST",
        body: JSON.stringify({ draft_token: draft.draft_token, name }),
      });
      await loadDevices();
      await loadDeviceStatuses();
      renderDeviceList();
      syncMapDeviceSelectOptions(document.getElementById("map-device"));
      pushToast(ui.toastArea, "Gerät angelegt", "success");
      modal.close();
    } catch (err) {
      setFieldState(nameField, "error", err.message);
      pushToast(ui.toastArea, err.message, "error");
    } finally {
      setButtonLoading(saveBtn, false);
    }
  });
  modal.open();
}

function renderDeviceList() {
  const list = document.getElementById("devices-list");
  if (!list) return;
  list.innerHTML = "";
  state.devices.forEach((device) => {
    const item = document.createElement("div");
    item.className = "list-item";
    const info = document.createElement("div");
    const status = state.deviceStatuses[device.id];
    const seen = status?.last_seen ? new Date(status.last_seen).toLocaleString("de-DE") : "Nie";
    const position =
      status?.latitude != null && status?.longitude != null
        ? `${Number(status.latitude).toFixed(5)}, ${Number(status.longitude).toFixed(5)}`
        : "Keine Position";
    info.innerHTML = `<strong>${device.name}</strong><br><small>${device.id}</small><br><small>Last Seen: ${seen}</small><br><small>Pos: ${position}</small>`;
    const actions = document.createElement("div");
    actions.className = "ui-item-actions";
    const copyKeyBtn = createButton({
      label: "Key kopieren",
      icon: "content_copy",
      onClick: async () => {
        try {
          await navigator.clipboard.writeText(device.api_key || "");
          pushToast(ui.toastArea, "API-Key kopiert", "success");
        } catch (_err) {
          pushToast(ui.toastArea, "Kopieren nicht möglich", "error");
        }
      },
    });
    const renameBtn = createButton({
      label: "Umbenennen",
      onClick: async () => {
        openRenameModal(device);
      },
    });
    const rotateBtn = createButton({
      label: "API-Key neu",
      onClick: async () => {
        openRotateKeyModal(device);
      },
    });
    const deleteBtn = createButton({
      label: "Löschen",
      onClick: async () => {
        openDeleteModal(device);
      },
    });
    deleteBtn.classList.add("btn-danger");
    actions.append(copyKeyBtn, renameBtn, rotateBtn, deleteBtn);
    item.append(info, actions);
    list.appendChild(item);
  });
}

function showApiKeyModal(device) {
  const keyField = createField({ label: `${device.name} API-Key`, value: device.api_key });
  keyField.input.readOnly = true;
  const copyBtn = createButton({
    label: "Key kopieren",
    icon: "content_copy",
    onClick: async () => {
      try {
        await navigator.clipboard.writeText(device.api_key);
        pushToast(ui.toastArea, "API-Key kopiert", "success");
      } catch (_err) {
        pushToast(ui.toastArea, "Kopieren nicht möglich", "error");
      }
    },
  });
  const content = document.createElement("div");
  content.append(keyField.field, copyBtn);
  openInfoModal({ title: "Gerät erstellt", content });
}

function openRenameModal(device) {
  openFormModal({
    title: "Gerät umbenennen",
    submitLabel: "Speichern",
    fields: [{ key: "name", label: "Neuer Name", value: device.name }],
    onSubmit: async (values, _controls, fieldMap) => {
      const nextName = String(values.name || "").trim();
      if (!nextName) {
        setFieldState(fieldMap.name, "error", "Bitte Namen eingeben.");
        throw new Error("invalid");
      }
      setFieldState(fieldMap.name, "success", "");
      try {
        await api(`/api/devices/${device.id}`, {
          method: "PUT",
          body: JSON.stringify({ name: nextName }),
        });
        await loadDevices();
        await loadDeviceStatuses();
        renderDeviceList();
        pushToast(ui.toastArea, "Gerät aktualisiert", "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
        throw err;
      }
    },
  });
}

function openDeleteModal(device) {
  openConfirmModal({
    title: "Löschen bestätigen",
    message: `Gerät "${device.name}" wirklich löschen?`,
    confirmLabel: "Löschen",
    onConfirm: async () => {
      try {
        await api(`/api/devices/${device.id}`, { method: "DELETE" });
        await loadDevices();
        await loadDeviceStatuses();
        renderDeviceList();
        pushToast(ui.toastArea, "Gerät gelöscht", "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
        throw err;
      }
    },
  });
}

function openRotateKeyModal(device) {
  openConfirmModal({
    title: "API-Key neu generieren",
    message: `Für "${device.name}" einen neuen API-Key erstellen? Der alte Key wird sofort ungültig.`,
    confirmLabel: "Neu generieren",
    onConfirm: async () => {
      try {
        const res = await api(`/api/devices/${device.id}/rotate-key`, { method: "POST" });
        showApiKeyModal(res.device);
        pushToast(ui.toastArea, "API-Key erneuert", "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
        throw err;
      }
    },
  });
}

function buildSettingsPage() {
  const page = document.getElementById("page-settings");
  page.innerHTML = `
    <div class="card settings-card">
      <section class="settings-section">
        <h3>Theme</h3>
        <div id="settings-theme" class="ui-form-grid"></div>
      </section>
      <section class="settings-section">
        <h3>Speicherung</h3>
        <div id="settings-storage" class="ui-form-grid"></div>
      </section>
      <section class="settings-section settings-diagnostics">
        <details class="settings-accordion">
          <summary>Systemstatus</summary>
          <div id="settings-system-status"></div>
        </details>
        <details class="settings-accordion">
          <summary>Forwarding Fehler</summary>
          <div id="settings-forwarding-errors"></div>
        </details>
        <details class="settings-accordion">
          <summary>Letzte GPS Requests</summary>
          <div id="settings-recent-gps"></div>
        </details>
      </section>
      <section class="settings-section">
        <h3>Weiterleitung</h3>
        <div id="settings-forwarding" class="settings-forwarding-block">
          <div id="forwarding-add-host"></div>
          <div id="forwardings-list" class="list ui-list"></div>
        </div>
      </section>
      <section class="settings-section">
        <h3>Geräte</h3>
        <div id="devices-create" class="ui-form-grid"></div>
        <div id="devices-list" class="list ui-list"></div>
      </section>
      <div id="settings-save-footer" class="settings-save-footer"></div>
    </div>
  `;
  const themeHost = page.querySelector("#settings-theme");
  const storageHost = page.querySelector("#settings-storage");
  const forwardingAddHost = page.querySelector("#forwarding-add-host");

  const nasInterval = createField({
    label: "NAS Intervall (Sekunden)",
    type: "number",
    value: String(state.settings.nas_interval_seconds || 60),
  });
  const nasPath = createField({ label: "NAS Pfad", value: state.settings.nas_path || "nas_storage" });
  const themeSelect = createField({ label: "Theme", type: "select" });
  themeSelect.input.innerHTML = state.themes.map((name) => `<option value="${name}">${name}</option>`).join("");
  themeSelect.input.value = state.settings.theme || "light";

  const saveNowBtn = createButton({
    label: "Jetzt GPS Informationen abspeichern",
    icon: "save",
    onClick: async () => {
      setButtonLoading(saveNowBtn, true, "Speichert...");
      try {
        const res = await api("/api/save-now", { method: "POST" });
        pushToast(ui.toastArea, `Gespeichert: ${res.result.saved_count}`, "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
      } finally {
        setButtonLoading(saveNowBtn, false);
      }
    },
  });
  saveNowBtn.classList.add("btn-secondary");

  const saveBtn = createButton({
    label: "Einstellungen speichern",
    icon: "check",
    onClick: async () => {
      setButtonLoading(saveBtn, true, "Speichert...");
      try {
        setFieldState(nasInterval, "default", "");

        const intervalValue = Number(nasInterval.input.value || 60);
        if (!Number.isFinite(intervalValue) || intervalValue < 5) {
          setFieldState(nasInterval, "error", "Intervall muss mindestens 5 Sekunden sein.");
          throw new Error("Bitte Eingaben prüfen");
        }

        const payload = {
          nas_interval_seconds: intervalValue,
          nas_path: nasPath.input.value.trim(),
          theme: themeSelect.input.value,
        };
        const data = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
        state.settings = data.settings;
        applyTheme(state.settings.theme);
        setFieldState(nasInterval, "success", "");
        pushToast(ui.toastArea, "Einstellungen gespeichert", "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
      } finally {
        setButtonLoading(saveBtn, false);
      }
    },
  });
  saveBtn.classList.add("btn-primary", "btn-settings-save");

  themeSelect.input.addEventListener("change", () => applyTheme(themeSelect.input.value));
  themeHost.append(themeSelect.field);
  storageHost.append(nasInterval.field, nasPath.field, saveNowBtn);
  const addFwBtn = createButton({
    label: "Neue Weiterleitung hinzufügen",
    icon: "add",
    onClick: () => openForwardingModal(null),
  });
  addFwBtn.classList.add("btn-primary");
  forwardingAddHost?.appendChild(addFwBtn);
  renderForwardingList();
  const saveFooter = page.querySelector("#settings-save-footer");
  saveFooter?.appendChild(saveBtn);
  renderDevicesSection();
  renderSystemStatus();
  renderForwardingErrors();
  renderRecentGps();
}

function openForwardingModal(existing) {
  const content = document.createElement("div");
  const nameField = createField({ label: "Name", value: existing?.name || "" });
  const urlField = createField({ label: "Forwarding-URL", value: existing?.url || "" });
  const headersField = createField({
    label: "Header JSON",
    type: "textarea",
    value: existing ? JSON.stringify(existing.headers || {}, null, 2) : "{}",
  });
  const ena = createSwitch({
    label: "Aktiviert",
    value: existing ? !!existing.enabled : true,
    onChange: () => {},
  });
  content.append(nameField.field, urlField.field, headersField.field, ena.wrap);
  const cancelBtn = createButton({ label: "Abbrechen" });
  const primaryLabel = existing ? "Speichern" : "Hinzufügen";
  const primaryBtn = createButton({ label: primaryLabel, icon: existing ? "check" : "add" });
  primaryBtn.classList.add("btn-primary");
  const modal = createModal({
    title: existing ? "Weiterleitung bearbeiten" : "Neue Weiterleitung",
    content,
    actions: [cancelBtn, primaryBtn],
  });
  cancelBtn.addEventListener("click", () => modal.close());
  primaryBtn.addEventListener("click", async () => {
    let headersObj = {};
    const raw = headersField.input.value.trim();
    if (raw) {
      try {
        headersObj = JSON.parse(raw);
        if (typeof headersObj !== "object" || Array.isArray(headersObj) || headersObj === null) {
          throw new Error("invalid");
        }
      } catch (_err) {
        setFieldState(headersField, "error", "Ungültiges JSON-Objekt.");
        return;
      }
    }
    setFieldState(headersField, "default", "");
    const enabled = ena.toggle.classList.contains("enabled");
    const name = nameField.input.value.trim();
    const url = urlField.input.value.trim();
    if (!name) {
      setFieldState(nameField, "error", "Name erforderlich.");
      return;
    }
    setFieldState(nameField, "default", "");
    if (!url) {
      setFieldState(urlField, "error", "URL erforderlich.");
      return;
    }
    if (!isHttpUrl(url)) {
      setFieldState(urlField, "error", "URL muss mit http:// oder https:// beginnen.");
      return;
    }
    setFieldState(urlField, "default", "");
    setButtonLoading(primaryBtn, true, "…");
    try {
      if (existing) {
        await api(`/api/forwardings/${existing.id}`, {
          method: "PUT",
          body: JSON.stringify({ name, url, headers: headersObj, enabled }),
        });
      } else {
        await api("/api/forwardings", {
          method: "POST",
          body: JSON.stringify({ name, url, headers: headersObj, enabled }),
        });
      }
      await loadSettings();
      renderForwardingList();
      pushToast(ui.toastArea, existing ? "Weiterleitung gespeichert" : "Weiterleitung hinzugefügt", "success");
      modal.close();
    } catch (err) {
      pushToast(ui.toastArea, err.message, "error");
    } finally {
      setButtonLoading(primaryBtn, false);
    }
  });
  modal.open();
}

function renderForwardingList() {
  const host = document.getElementById("forwardings-list");
  if (!host) return;
  host.innerHTML = "";
  const list = state.settings?.forwardings;
  if (!Array.isArray(list) || list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "list-item list-placeholder";
    empty.textContent = "Keine Weiterleitungen angelegt.";
    host.appendChild(empty);
    return;
  }
  list.forEach((f) => {
    const item = document.createElement("div");
    item.className = "list-item list-item-managed";
    const leading = document.createElement("div");
    leading.className = "list-item-leading";
    const sw = createSwitch({
      value: !!f.enabled,
      onChange: async (next) => {
        try {
          await api(`/api/forwardings/${f.id}`, { method: "PATCH", body: JSON.stringify({ enabled: next }) });
          await loadSettings();
          renderForwardingList();
        } catch (err) {
          sw.toggle.classList.toggle("enabled", !next);
          pushToast(ui.toastArea, err.message, "error");
        }
      },
    });
    leading.appendChild(sw.wrap);
    const body = document.createElement("div");
    body.className = "list-item-body";
    const t = document.createElement("strong");
    t.textContent = f.name || "Weiterleitung";
    const u = document.createElement("small");
    u.textContent = f.url || "";
    body.append(t, document.createElement("br"), u);
    const actions = document.createElement("div");
    actions.className = "ui-item-actions";
    const editBtn = createButton({
      label: "Bearbeiten",
      onClick: () => openForwardingModal(f),
    });
    const delBtn = createButton({
      label: "Löschen",
      onClick: () => openDeleteForwardingModal(f),
    });
    delBtn.classList.add("btn-danger");
    actions.append(editBtn, delBtn);
    item.append(leading, body, actions);
    host.appendChild(item);
  });
}

function openDeleteForwardingModal(f) {
  openConfirmModal({
    title: "Weiterleitung löschen",
    message: `Weiterleitung „${f.name}“ wirklich löschen?`,
    confirmLabel: "Löschen",
    onConfirm: async () => {
      try {
        await api(`/api/forwardings/${f.id}`, { method: "DELETE" });
        await loadSettings();
        renderForwardingList();
        pushToast(ui.toastArea, "Weiterleitung gelöscht", "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
        throw err;
      }
    },
  });
}

function renderSystemStatus() {
  const host = document.getElementById("settings-system-status");
  if (!host) return;
  const status = state.systemStatus || {};
  const uptime = Number(status.uptime_seconds || 0);
  const h = Math.floor(uptime / 3600);
  const m = Math.floor((uptime % 3600) / 60);
  const s = uptime % 60;
  const lastNasRun = status.last_nas_run_at ? new Date(status.last_nas_run_at).toLocaleString("de-DE") : "Noch kein Lauf";
  const lastNasError = status.last_nas_error || "Kein Fehler";
  host.innerHTML = `
    <div class="list">
      <div class="list-item"><span>Uptime</span><strong>${h}h ${m}m ${s}s</strong></div>
      <div class="list-item"><span>Geräte</span><strong>${status.device_count ?? 0}</strong></div>
      <div class="list-item"><span>Forwarding Queue</span><strong>${status.forward_queue_size ?? 0}</strong></div>
      <div class="list-item"><span>Pending NAS</span><strong>${status.pending_nas_count ?? 0}</strong></div>
      <div class="list-item"><span>Gespeicherte Statusobjekte</span><strong>${status.stored_status_count ?? 0}</strong></div>
      <div class="list-item"><span>Letzter NAS-Lauf</span><strong>${lastNasRun}</strong></div>
      <div class="list-item"><span>Beim letzten NAS-Lauf gespeichert</span><strong>${status.last_nas_saved_count ?? 0}</strong></div>
      <div class="list-item"><span>NAS Fehlerstatus</span><small>${lastNasError}</small></div>
    </div>
  `;
}

function renderForwardingErrors() {
  const host = document.getElementById("settings-forwarding-errors");
  if (!host) return;
  const errors = state.forwardingErrors || [];
  const rows = errors.length
    ? errors
        .map(
          (entry) =>
            `<div class="list-item"><span>${new Date(entry.time).toLocaleString("de-DE")}</span><small>${entry.message}</small></div>`,
        )
        .join("")
    : `<div class="list-item"><span>Keine Forwarding-Fehler</span></div>`;
  host.innerHTML = `
    <div class="panel-head">
      <div class="panel-actions">
        <button id="reload-forwarding-errors" class="btn">Neu laden</button>
        <button id="clear-forwarding-errors" class="btn">Leeren</button>
      </div>
    </div>
    <div class="list">${rows}</div>
  `;
  const btn = host.querySelector("#reload-forwarding-errors");
  btn?.addEventListener("click", async () => {
    setButtonLoading(btn, true, "Lädt...");
    try {
      await loadForwardingErrors();
      renderForwardingErrors();
    } finally {
      setButtonLoading(btn, false);
    }
  });
  const clearBtn = host.querySelector("#clear-forwarding-errors");
  clearBtn?.addEventListener("click", async () => {
    setButtonLoading(clearBtn, true, "Löscht...");
    try {
      await api("/api/forwarding/errors/clear", { method: "POST" });
      await loadForwardingErrors();
      renderForwardingErrors();
    } finally {
      setButtonLoading(clearBtn, false);
    }
  });
}

function renderRecentGps() {
  const host = document.getElementById("settings-recent-gps");
  if (!host) return;
  const rows = (state.recentGps || [])
    .map(
      (entry) =>
        `<div class="list-item"><span>${entry.device_name || entry.device_id || "Unbekannt"} | ${new Date(entry.timestamp).toLocaleString("de-DE")}</span><small>${entry.latitude}, ${entry.longitude} (acc: ${entry.accuracy ?? "-"})</small></div>`,
    )
    .join("");
  host.innerHTML = `
    <div class="panel-head">
      <div class="panel-actions">
        <button id="reload-recent-gps" class="btn">Neu laden</button>
      </div>
    </div>
    <div class="list">${rows || `<div class="list-item"><span>Keine GPS-Daten</span></div>`}</div>
  `;
  const btn = host.querySelector("#reload-recent-gps");
  btn?.addEventListener("click", async () => {
    setButtonLoading(btn, true, "Lädt...");
    try {
      await loadRecentGps();
      renderRecentGps();
    } finally {
      setButtonLoading(btn, false);
    }
  });
}

function applyTheme(name) {
  let link = document.getElementById("theme-link");
  if (!link) {
    link = document.createElement("link");
    link.id = "theme-link";
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  link.href = `/themes/${name}/theme.css`;
}

async function loadDevices() {
  const data = await api("/api/devices");
  state.devices = data.devices || [];
  const mapSelect = document.getElementById("map-device");
  syncMapDeviceSelectOptions(mapSelect);
}

async function loadDeviceStatuses() {
  const data = await api("/api/devices/status");
  state.deviceStatuses = data.statuses || {};
}

async function loadSettings() {
  const data = await api("/api/settings");
  state.settings = data.settings || {};
}

async function loadThemes() {
  const data = await api("/api/themes");
  state.themes = data.themes || ["light"];
}

async function loadSystemStatus() {
  const data = await api("/api/system/status");
  state.systemStatus = data.status || {};
}

async function loadForwardingErrors() {
  const data = await api("/api/forwarding/errors?limit=20");
  state.forwardingErrors = data.errors || [];
}

async function loadRecentGps() {
  const data = await api("/api/gps/recent?limit=20");
  state.recentGps = data.requests || [];
}

bootstrap().catch((err) => {
  console.error(err);
  alert(`Init Fehler: ${err.message}`);
});
