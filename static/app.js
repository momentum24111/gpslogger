import {
  createButton,
  createField,
  createIconButton,
  createModal,
  configureI18n,
  createSwitch,
  createToastArea,
  openConfirmModal,
  openFormModal,
  openInfoModal,
  pushToast,
  setFieldState,
  setButtonLoading,
  readModalAnimationDurationMs,
} from "/static/ui-components.js";
import { initInkRipple } from "/static/ripple.js";

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const LANGUAGE_STORAGE_KEY = "gpslogger.language";
const DEFAULT_LANGUAGE = "de";
const SUPPORTED_LANGUAGES = ["de", "en"];
let translations = {};
let currentLanguage = DEFAULT_LANGUAGE;

function t(key, vars = {}, fallback = "") {
  const segments = String(key || "").split(".");
  let value = translations;
  for (const segment of segments) {
    value = value?.[segment];
  }
  const base = typeof value === "string" ? value : fallback || key;
  return base.replace(/\{(\w+)\}/g, (_m, token) => (vars[token] == null ? "" : String(vars[token])));
}

function updateVisibleTexts() {
  const mapSidebarToggle = document.getElementById("map-sidebar-toggle");
  const brandHomeButton = document.getElementById("brand-home");
  if (mapSidebarToggle) {
    const isExpanded = mapSidebarToggle.getAttribute("aria-expanded") === "true";
    mapSidebarToggle.setAttribute("aria-label", isExpanded ? t("map.menuClose") : t("map.menuOpen"));
  }
  if (brandHomeButton) {
    brandHomeButton.setAttribute("aria-label", t("app.goToMap"));
  }

  const mapDeviceListLabel = document.getElementById("map-device-list-label");
  if (mapDeviceListLabel) mapDeviceListLabel.textContent = t("settings.devices.title");
  const mapDeviceList = document.getElementById("map-device-list");
  if (mapDeviceList) mapDeviceList.setAttribute("aria-label", t("map.devices.toggleAria"));
  const mapRangeLabel = document.getElementById("map-range-label");
  if (mapRangeLabel) mapRangeLabel.textContent = t("map.range.title");
  const mapStatusBtn = document.getElementById("map-status-btn");
  if (mapStatusBtn) mapStatusBtn.innerHTML = `<span class="material-symbols-outlined">monitoring</span> ${t("status.title")}`;
  const mapSettingsBtn = document.getElementById("map-settings-btn");
  if (mapSettingsBtn) mapSettingsBtn.innerHTML = `<span class="material-symbols-outlined">settings</span> ${t("settings.title")}`;
  const settingsSaveNowBtn = document.getElementById("settings-save-now-btn");
  if (settingsSaveNowBtn) settingsSaveNowBtn.innerHTML = `<span class="material-symbols-outlined">save</span> ${t("settings.storage.saveNow")}`;
  const settingsRestartBtn = document.getElementById("settings-restart-btn");
  if (settingsRestartBtn) settingsRestartBtn.innerHTML = `<span class="material-symbols-outlined">refresh</span> ${t("settings.actions.restart")}`;
  const settingsSaveBtn = document.getElementById("settings-save-btn");
  if (settingsSaveBtn) settingsSaveBtn.innerHTML = `<span class="material-symbols-outlined">check</span> ${t("settings.save")}`;
  const settingsCancelBtn = document.getElementById("settings-cancel-btn");
  if (settingsCancelBtn) settingsCancelBtn.innerHTML = `<span class="material-symbols-outlined">close</span> ${t("settings.cancel")}`;
  const settingsForwardingLabel = document.getElementById("settings-forwardings-label");
  if (settingsForwardingLabel) settingsForwardingLabel.textContent = t("settings.forwardings.title");
  const settingsDevicesLabel = document.getElementById("settings-devices-label");
  if (settingsDevicesLabel) settingsDevicesLabel.textContent = t("settings.devices.title");
  const addForwardingBtn = document.getElementById("settings-add-forwarding-btn");
  if (addForwardingBtn) {
    addForwardingBtn.innerHTML = `<span class="material-symbols-outlined">add</span> ${t("settings.forwardings.add")}`;
    addForwardingBtn.setAttribute("aria-label", t("settings.forwardings.add"));
  }
  const addDeviceBtn = document.getElementById("settings-add-device-btn");
  if (addDeviceBtn) {
    addDeviceBtn.innerHTML = `<span class="material-symbols-outlined">add</span> ${t("settings.devices.add")}`;
    addDeviceBtn.setAttribute("aria-label", t("settings.devices.add"));
  }

  const rangeLabelByValue = {
    [MAP_RANGE_CURRENT]: t("map.range.current"),
    "1h": t("map.range.last1h"),
    "6h": t("map.range.last6h"),
    "24h": t("map.range.last24h"),
    "7d": t("map.range.last7d"),
    "30d": t("map.range.last30d"),
    custom: t("map.range.custom"),
  };
  Object.entries(rangeLabelByValue).forEach(([value, text]) => {
    const input = document.querySelector(`input[name="map-range"][value="${value}"]`);
    if (!input?.id) return;
    const label = document.querySelector(`label[for="${input.id}"]`);
    if (label) {
      const badge = label.querySelector(".map-range-count");
      label.textContent = text;
      if (badge) label.appendChild(badge);
    }
  });

  const fromLabel = document.querySelector('#map-from')?.closest(".field")?.querySelector("span");
  const toLabel = document.querySelector('#map-to')?.closest(".field")?.querySelector("span");
  if (fromLabel) fromLabel.textContent = t("map.range.fromDate");
  if (toLabel) toLabel.textContent = t("map.range.toDate");

  const settingsTitle = document.getElementById("settings-title-text");
  if (settingsTitle) settingsTitle.textContent = t("settings.title");
  const settingsCloseBtn = document.querySelector(".settings-modal-close");
  if (settingsCloseBtn) settingsCloseBtn.setAttribute("aria-label", t("settings.close"));
  const settingsSystemTitle = document.getElementById("settings-system-title");
  if (settingsSystemTitle) settingsSystemTitle.textContent = t("settings.system.title");
  const settingsStorageTitle = document.getElementById("settings-storage-title");
  if (settingsStorageTitle) settingsStorageTitle.textContent = t("settings.storage.title");
  const settingsForwardingsTitle = document.getElementById("settings-forwardings-title");
  if (settingsForwardingsTitle) settingsForwardingsTitle.textContent = t("settings.forwardings.title");
  const settingsDevicesTitle = document.getElementById("settings-devices-title");
  if (settingsDevicesTitle) settingsDevicesTitle.textContent = t("settings.devices.title");
  const settingsActionsLabel = document.querySelector(".settings-action-label");
  if (settingsActionsLabel) settingsActionsLabel.textContent = t("settings.actions.title");
  if (ui.settingsFormRefs?.nasInterval?.field) {
    const lbl = ui.settingsFormRefs.nasInterval.field.querySelector("span");
    if (lbl) lbl.textContent = t("settings.storage.nasInterval");
  }
  if (ui.settingsFormRefs?.nasPath?.field) {
    const lbl = ui.settingsFormRefs.nasPath.field.querySelector("span");
    if (lbl) lbl.textContent = t("settings.storage.nasPath");
  }
  if (ui.settingsFormRefs?.themeSelect?.field) {
    const lbl = ui.settingsFormRefs.themeSelect.field.querySelector("span");
    if (lbl) lbl.textContent = t("settings.system.theme");
  }
  if (ui.settingsFormRefs?.languageSelect?.field) {
    const lbl = ui.settingsFormRefs.languageSelect.field.querySelector("span");
    if (lbl) lbl.textContent = t("settings.system.language");
    ui.settingsFormRefs.languageSelect.input.innerHTML = SUPPORTED_LANGUAGES.map((lang) => `<option value="${lang}">${t(`language.${lang}`)}</option>`).join("");
    ui.settingsFormRefs.languageSelect.input.value = currentLanguage;
  }
  const addFwBtn = document.querySelector("#forwarding-add-host .btn");
  if (addFwBtn) {
    addFwBtn.title = t("settings.forwardings.add");
    addFwBtn.setAttribute("aria-label", t("settings.forwardings.add"));
  }

  document.querySelectorAll("#forwardings-list .list-item-managed").forEach((item) => {
    const name = item.dataset.forwardingName || "";
    const titleEl = item.querySelector(".list-item-body strong");
    if (titleEl && !name) titleEl.textContent = t("settings.forwardings.fallbackName");
    const metaEl = item.querySelector(".list-item-meta");
    if (metaEl) {
      const bits = [];
      if (item.dataset.incomingHeadersOnly === "false") bits.push(t("settings.forwardings.summary.headerManual"));
      if (item.dataset.forwardBodyFromSource === "false") bits.push(t("settings.forwardings.summary.bodyEmpty"));
      metaEl.textContent = bits.join(" · ");
    }
    const testBtn = item.querySelector('[data-forwarding-action="test"]');
    if (testBtn) {
      testBtn.title = t("settings.forwardings.test");
      testBtn.setAttribute("aria-label", t("settings.forwardings.testAria", { name }));
    }
    const editBtn = item.querySelector('[data-forwarding-action="edit"]');
    if (editBtn) {
      editBtn.title = t("common.edit");
      editBtn.setAttribute("aria-label", t("settings.forwardings.editAria", { name }));
    }
    const delBtn = item.querySelector('[data-forwarding-action="delete"]');
    if (delBtn) {
      delBtn.title = t("common.delete");
      delBtn.setAttribute("aria-label", t("settings.forwardings.deleteAria", { name }));
    }
  });

  const statusModalTitle = document.querySelector('.modal-overlay .modal-head h3');
  if (ui.statusModalOpen && statusModalTitle) {
    statusModalTitle.innerHTML = '<span class="material-symbols-outlined" aria-hidden="true">monitoring</span><span>' + t("status.title") + "</span>";
  }
  const statusSystemTitle = document.getElementById("status-system-title");
  const statusForwardingTitle = document.getElementById("status-forwarding-title");
  const statusRecentGpsTitle = document.getElementById("status-recent-gps-title");
  if (statusSystemTitle) statusSystemTitle.textContent = t("status.system.title");
  if (statusForwardingTitle) statusForwardingTitle.textContent = t("status.forwardingErrors.title");
  if (statusRecentGpsTitle) statusRecentGpsTitle.textContent = t("status.recentGps.title");

  renderSystemStatus(ui.statusModalHost?.querySelector("#status-system-status") || null);
  renderForwardingErrors(ui.statusModalHost?.querySelector("#status-forwarding-errors") || null);
  renderRecentGps(ui.statusModalHost?.querySelector("#status-recent-gps") || null);
}

async function loadLanguage(language) {
  const normalized = SUPPORTED_LANGUAGES.includes(language) ? language : DEFAULT_LANGUAGE;
  const res = await fetch(`/static/languages/${normalized}.json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load language file: ${normalized}`);
  translations = await res.json();
  currentLanguage = normalized;
  localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
  document.documentElement.lang = normalized;
  configureI18n((key, fallback) => t(key, {}, fallback || key));
}

/** Relative Zeit bis zum angegebenen Zeitpunkt (nur Vergangenheit). */
function formatRelativeTime(isoString) {
  const ts = new Date(isoString).getTime();
  if (Number.isNaN(ts)) return t("common.na", {}, "-");
  const diffMs = Math.max(0, Date.now() - ts);
  const sec = Math.floor(diffMs / 1000);
  if (sec < 45) return t("time.justNow");
  const min = Math.floor(diffMs / 60000);
  if (min < 60) return min === 1 ? t("time.minuteOne") : t("time.minuteMany", { count: min });
  const h = Math.floor(min / 60);
  if (h < 24) return h === 1 ? t("time.hourOne") : t("time.hourMany", { count: h });
  const d = Math.floor(h / 24);
  if (d < 7) return d === 1 ? t("time.dayOne") : t("time.dayMany", { count: d });
  const w = Math.floor(d / 7);
  if (w < 5) return w === 1 ? t("time.weekOne") : t("time.weekMany", { count: w });
  const mo = Math.floor(d / 30);
  if (mo < 12) return mo === 1 ? t("time.monthOne") : t("time.monthMany", { count: mo });
  const y = Math.floor(d / 365);
  return y === 1 ? t("time.yearOne") : t("time.yearMany", { count: y });
}

const ui = {
  pages: {},
  toastArea: null,
  map: null,
  mapFitControl: null,
  layers: {},
  markers: new Map(),
  liveLabelMarkers: [],
  routeLines: [],
  mapMode: localStorage.getItem("gpslogger.map.mode") || "satellite",
  autoRefreshHandle: null,
  mapRange: localStorage.getItem("gpslogger.map.range") || "24h",
  positionEventSource: null,
  sseReconnectTimer: null,
  mapPickerCloseInitialized: false,
  routePointMarkers: [],
  pinnedRouteTooltipMarker: null,
  floatingColorPicker: null,
  settingsModalOpen: false,
  mapLayoutEl: null,
  mapDrawerBackdropEl: null,
  mapSidebarToggleEl: null,
  mapSidebarListenersBound: false,
  mapSidebarDelegatedClick: false,
  mapSidebarMqBound: false,
  mapSidebarDesktopMode: null,
  mapSidebarDrawerOpen: null,
  settingsDirty: false,
  settingsUnsavedDialogOpen: false,
  settingsEscKeyListener: null,
  statusModalOpen: false,
  statusModalHost: null,
};

const MAP_COLOR_COUNT = 6;
const MAP_RANGE_CURRENT = "current";
const STORAGE_VISIBLE = "gpslogger.map.visibleDeviceIds";
const STORAGE_DEVICE_SNAPSHOT = "gpslogger.map.deviceIdsSnapshot";
const SETTINGS_HASH = "#settings";
const FORWARDING_BODY_VARIABLES = [
  { key: "latitude", labelKey: "settings.forwardings.bodyVars.latitude" },
  { key: "longitude", labelKey: "settings.forwardings.bodyVars.longitude" },
  { key: "request_device", labelKey: "settings.forwardings.bodyVars.requestDevice" },
  { key: "device_name", labelKey: "settings.forwardings.bodyVars.deviceName" },
  { key: "accuracy", labelKey: "settings.forwardings.bodyVars.accuracy" },
  { key: "battery", labelKey: "settings.forwardings.bodyVars.battery" },
  { key: "speed", labelKey: "settings.forwardings.bodyVars.speed" },
  { key: "direction", labelKey: "settings.forwardings.bodyVars.direction" },
  { key: "altitude", labelKey: "settings.forwardings.bodyVars.altitude" },
  { key: "provider", labelKey: "settings.forwardings.bodyVars.provider" },
  { key: "activity", labelKey: "settings.forwardings.bodyVars.activity" },
  { key: "timestamp", labelKey: "settings.forwardings.bodyVars.timestamp" },
  { key: "device_id", labelKey: "settings.forwardings.bodyVars.deviceId" }
];

const state = {
  devices: [],
  deviceStatuses: {},
  settings: {},
  systemStatus: {},
  forwardingErrors: [],
  recentGps: [],
  themes: [],
  visibleDeviceIds: new Set(),
  lastForwardingTestResult: null,
};

/** Verhindert parallele Neustart-Workflows (Button / Modal). */
let gpsloggerRestartWorkflowActive = false;

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
  if (!res.ok) throw new Error(data.error || t("errors.api"));
  return data;
}

async function runGpsloggerRestart(button) {
  if (gpsloggerRestartWorkflowActive) return;
  gpsloggerRestartWorkflowActive = true;
  if (button) {
    button.disabled = true;
  }
  try {
    await api("/api/admin/restart", { method: "POST", body: "{}" });
  } catch (err) {
    gpsloggerRestartWorkflowActive = false;
    if (button) button.disabled = false;
    pushToast(ui.toastArea, err.message, "error");
    return;
  }

  const content = document.createElement("div");
  content.className = "restart-wait-modal-body";
  const spin = document.createElement("div");
  spin.className = "restart-wait-spinner";
  spin.setAttribute("aria-hidden", "true");
  const text = document.createElement("p");
  text.className = "restart-wait-text";
  text.textContent = t("settings.actions.restartInProgress");
  content.append(spin, text);

  const modal = createModal({
    title: t("settings.actions.restart"),
    content,
    actions: [],
    closeOnEscape: false,
    closeOnBackdrop: false,
  });
  modal.open();

  let pollTimer = null;
  const clearPoll = () => {
    if (pollTimer != null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  };

  const pollHealth = async () => {
    try {
      const res = await fetch("/api/health", { method: "GET", cache: "no-store" });
      if (res.ok) {
        clearPoll();
        modal.close();
        window.location.hash = "#map";
        window.location.reload();
        return;
      }
    } catch (_e) {
      /* Dienst noch nicht erreichbar */
    }
    pollTimer = setTimeout(pollHealth, 3000);
  };

  pollTimer = setTimeout(pollHealth, 2000);
}

async function bootstrap() {
  await loadLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY) || DEFAULT_LANGUAGE);
  ui.toastArea = createToastArea();
  document.body.appendChild(ui.toastArea);
  initInkRipple();
  const mapSidebarToggle = document.getElementById("map-sidebar-toggle");
  const brandHomeButton = document.getElementById("brand-home");
  if (mapSidebarToggle) mapSidebarToggle.setAttribute("aria-label", t("map.menuOpen"));
  if (brandHomeButton) brandHomeButton.setAttribute("aria-label", t("app.goToMap"));

  await Promise.all([loadDevices(), loadDeviceStatuses(), loadSettings(), loadThemes(), loadSystemStatus(), loadForwardingErrors()]);
  applyTheme(state.settings.theme || "light");
  buildMapPage();
  buildSettingsPage();
  initMapSidebarDrawer();
  initSettingsHashRouting();
  connectPositionStream();
  const brandHome = document.getElementById("brand-home");
  brandHome?.addEventListener("click", () => {
    closeSettingsModal();
    closeMapSidebarDrawer();
  });
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
  registerServiceWorker();
}

async function runAutoRefreshCycle() {
  try {
    await refreshMapData({ preserveView: true });
    if (ui.settingsModalOpen) {
      await loadSettings();
      await loadDevices();
      await loadDeviceStatuses();
      renderForwardingList();
      renderDeviceList();
    }
    if (ui.statusModalOpen) {
      await loadSystemStatus();
      await loadForwardingErrors();
      await loadRecentGps();
      renderStatusModalContent();
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

function migrateMapDeviceSelection() {
  if (localStorage.getItem(STORAGE_VISIBLE) !== null) return;
  const single = localStorage.getItem("gpslogger.selectedDeviceId") || "";
  if (single) {
    localStorage.setItem(STORAGE_VISIBLE, JSON.stringify([single]));
  }
  localStorage.removeItem("gpslogger.selectedDeviceId");
}

function syncVisibleDevicesWithLoadedDevices() {
  const currentIds = new Set(state.devices.map((d) => d.id));
  let prevSnap = new Set();
  try {
    const snapRaw = localStorage.getItem(STORAGE_DEVICE_SNAPSHOT);
    if (snapRaw) prevSnap = new Set(JSON.parse(snapRaw));
  } catch {
    prevSnap = new Set();
  }
  const raw = localStorage.getItem(STORAGE_VISIBLE);
  let filtered;
  if (raw === null) {
    filtered = [...currentIds];
  } else {
    try {
      filtered = JSON.parse(raw);
      if (!Array.isArray(filtered)) filtered = [];
    } catch {
      filtered = [];
    }
    filtered = filtered.filter((id) => currentIds.has(id));
    currentIds.forEach((id) => {
      if (!prevSnap.has(id) && !filtered.includes(id)) filtered.push(id);
    });
  }
  localStorage.setItem(STORAGE_DEVICE_SNAPSHOT, JSON.stringify([...currentIds]));
  state.visibleDeviceIds = new Set(filtered);
  localStorage.setItem(STORAGE_VISIBLE, JSON.stringify(filtered));
}

function saveVisibleDeviceIds() {
  localStorage.setItem(STORAGE_VISIBLE, JSON.stringify([...state.visibleDeviceIds]));
}

function toggleDeviceVisibility(deviceId) {
  if (state.visibleDeviceIds.has(deviceId)) state.visibleDeviceIds.delete(deviceId);
  else state.visibleDeviceIds.add(deviceId);
  saveVisibleDeviceIds();
}

function getDeviceColorIndex(deviceId) {
  const d = state.devices.find((x) => x.id === deviceId);
  const idx = d?.map_color_index;
  return typeof idx === "number" && idx >= 0 && idx < MAP_COLOR_COUNT ? idx : 0;
}

function resolvePaletteColor(index) {
  const resolved = getComputedStyle(document.documentElement).getPropertyValue(`--device-map-palette-${index}`).trim();
  return resolved || getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim();
}

function getMapCssVar(name, fallback = "") {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function getMapCssNumber(name, fallback) {
  const raw = getMapCssVar(name, "");
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatMetricValue(value, unit = "") {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return `${escapeHtml(String(value))}${unit ? ` ${unit}` : ""}`;
  return `${Math.round(n)}${unit ? ` ${unit}` : ""}`;
}

function formatBatteryValue(value) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isFinite(n)) return `${Math.round(n)} %`;
  return escapeHtml(String(value));
}

function buildPositionTooltipHtml(position, deviceNameFallback = "") {
  const deviceName = position.device_name || deviceNameFallback || position.device_id || "Unbekannt";
  const lat = Number(position.latitude);
  const lon = Number(position.longitude);
  const latText = Number.isFinite(lat) ? lat.toFixed(6) : "—";
  const lonText = Number.isFinite(lon) ? lon.toFixed(6) : "—";
  const mapsUrl = `https://www.google.com/maps?q=${encodeURIComponent(`${latText},${lonText}`)}`;
  const rows = [
    ["Zeit", escapeHtml(String(position.timestamp || "—"))],
    ["Lat", escapeHtml(latText)],
    ["Lon", escapeHtml(lonText)],
    ["Genauigkeit", escapeHtml(formatMetricValue(position.accuracy, "m"))],
    ["Akku", escapeHtml(formatBatteryValue(position.battery))],
    ["Geschw.", escapeHtml(formatMetricValue(position.speed, "km/h"))],
    ["Richtung", escapeHtml(formatMetricValue(position.direction, "°"))],
    ["Höhe", escapeHtml(formatMetricValue(position.altitude, "m"))],
  ];
  return `<div class="map-tooltip-content"><div class="map-tooltip-title">${escapeHtml(String(deviceName))}</div><div class="map-tooltip-grid">${rows
    .map(([label, value]) => `<span class="map-tooltip-label">${label}</span><span class="map-tooltip-value">${value}</span>`)
    .join("")}</div><div class="map-tooltip-actions"><a class="map-tooltip-maps-link btn" href="${mapsUrl}" target="_blank" rel="noopener noreferrer"><span class="material-symbols-outlined" aria-hidden="true">open_in_new</span><span>Google Maps öffnen</span></a></div></div>`;
}

function getDeviceDisplayName(deviceId, fallback = "") {
  const device = state.devices.find((entry) => entry.id === deviceId);
  return device?.name || fallback || deviceId || "";
}

function getDeviceInitial(deviceName) {
  return String(deviceName || "?").trim().charAt(0) || "?";
}

function addLivePointInitialMarker(latLng, deviceName) {
  const radius = getMapCssNumber("--map-live-point-radius", 7);
  const diameter = Math.max(1, radius * 2);
  const marker = L.marker(latLng, {
    interactive: false,
    keyboard: false,
    icon: L.divIcon({
      className: "map-live-point-initial",
      html: `<span>${escapeHtml(getDeviceInitial(deviceName))}</span>`,
      iconSize: [diameter, diameter],
      iconAnchor: [radius, radius],
    }),
  }).addTo(ui.map);
  ui.liveLabelMarkers.push(marker);
}

function closePinnedRouteTooltip() {
  if (!ui.pinnedRouteTooltipMarker) return;
  ui.pinnedRouteTooltipMarker.__tooltipPinned = false;
  const pinnedTooltip = ui.pinnedRouteTooltipMarker.getTooltip?.();
  if (pinnedTooltip) pinnedTooltip.options.permanent = false;
  ui.pinnedRouteTooltipMarker.closeTooltip();
  ui.pinnedRouteTooltipMarker = null;
}

function bindRoutePointInteractions(marker) {
  const baseRadius = getMapCssNumber("--map-route-point-radius", 3);
  const hoverRadius = getMapCssNumber("--map-route-point-hover-radius", 8);
  marker.__tooltipPinned = false;
  marker.on("mouseover", () => {
    marker.setRadius(hoverRadius);
    marker.openTooltip();
  });
  marker.on("mouseout", () => {
    marker.setRadius(baseRadius);
    if (!marker.__tooltipPinned) marker.closeTooltip();
  });
  marker.on("tooltipclose", () => {
    if (marker.__tooltipPinned) marker.openTooltip();
  });
  marker.on("click", (event) => {
    if (ui.pinnedRouteTooltipMarker && ui.pinnedRouteTooltipMarker !== marker) {
      ui.pinnedRouteTooltipMarker.__tooltipPinned = false;
      const currentPinnedTooltip = ui.pinnedRouteTooltipMarker.getTooltip?.();
      if (currentPinnedTooltip) currentPinnedTooltip.options.permanent = false;
      ui.pinnedRouteTooltipMarker.closeTooltip();
    }
    marker.__tooltipPinned = true;
    ui.pinnedRouteTooltipMarker = marker;
    const tooltip = marker.getTooltip?.();
    if (tooltip) tooltip.options.permanent = true;
    marker.setRadius(hoverRadius);
    marker.openTooltip();
    if (event?.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
  });
}

function clearMapOverlays() {
  ui.markers.forEach((marker) => ui.map.removeLayer(marker));
  ui.markers.clear();
  ui.liveLabelMarkers.forEach((marker) => ui.map.removeLayer(marker));
  ui.liveLabelMarkers = [];
  ui.routeLines.forEach((line) => ui.map.removeLayer(line));
  ui.routeLines = [];
  ui.routePointMarkers.forEach((marker) => ui.map.removeLayer(marker));
  ui.routePointMarkers = [];
  closePinnedRouteTooltip();
}

async function drawCurrentPositionsOnly({ preserveView = false } = {}) {
  clearMapOverlays();
  await loadDeviceStatuses();
  const allLatLng = [];
  let renderedCount = 0;
  state.devices.forEach((device) => {
    if (!state.visibleDeviceIds.has(device.id)) return;
    const st = state.deviceStatuses[device.id];
    if (!st || st.latitude == null || st.longitude == null) return;
    const colorIdx = getDeviceColorIndex(device.id);
    const fill = resolvePaletteColor(colorIdx);
    const livePoint = {
      ...st,
      device_id: device.id,
      device_name: device.name,
      latitude: Number(st.latitude),
      longitude: Number(st.longitude),
      timestamp: st.last_seen || "",
    };
    const marker = L.circleMarker([livePoint.latitude, livePoint.longitude], {
      radius: getMapCssNumber("--map-live-point-radius", 7),
      fillColor: fill,
      color: getMapCssVar("--map-live-point-border"),
      weight: getMapCssNumber("--map-live-point-border-width", 2),
      fillOpacity: getMapCssNumber("--map-live-point-fill-opacity", 1),
      opacity: getMapCssNumber("--map-live-point-stroke-opacity", 1),
      className: "map-live-point map-live-point--pulse",
    }).addTo(ui.map);
    marker.bindTooltip(escapeHtml(formatRelativeTime(livePoint.timestamp)), {
      permanent: true,
      direction: "top",
      offset: [0, -24],
      className: "map-live-age-tooltip",
    });
    marker.bindPopup(buildPositionTooltipHtml(livePoint, device.name), {
      className: "map-point-tooltip",
    });
    addLivePointInitialMarker([livePoint.latitude, livePoint.longitude], device.name);
    ui.markers.set(device.id, marker);
    allLatLng.push([livePoint.latitude, livePoint.longitude]);
    renderedCount += 1;
  });
  if (!preserveView && allLatLng.length) {
    const bounds = L.latLngBounds(allLatLng);
    if (bounds.isValid()) ui.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 18 });
  }
  return renderedCount;
}

function closeFloatingColorPicker() {
  if (ui.floatingColorPicker) {
    ui.floatingColorPicker.remove();
    ui.floatingColorPicker = null;
  }
}

function openFloatingColorPicker(anchorButton, device, currentColorIdx) {
  closeFloatingColorPicker();
  const picker = document.createElement("div");
  picker.className = "map-color-picker map-color-picker-floating is-open";
  picker.dataset.deviceId = device.id;
  for (let i = 0; i < MAP_COLOR_COUNT; i++) {
    const sw = document.createElement("button");
    sw.type = "button";
    sw.className = `map-color-swatch map-color-swatch--${i}`;
    sw.setAttribute("aria-label", `Farbe ${i + 1}`);
    if (i === currentColorIdx) sw.classList.add("is-selected");
    sw.addEventListener("click", async (e) => {
      e.stopPropagation();
      closeFloatingColorPicker();
      if (i === currentColorIdx) return;
      try {
        const res = await api(`/api/devices/${device.id}`, {
          method: "PUT",
          body: JSON.stringify({ name: device.name, map_color_index: i }),
        });
        const updated = res.device;
        const ix = state.devices.findIndex((d) => d.id === updated.id);
        if (ix >= 0) state.devices[ix] = updated;
        renderMapDeviceList();
        await refreshMapData({ preserveView: true });
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
      }
    });
    picker.appendChild(sw);
  }
  document.body.appendChild(picker);
  const rect = anchorButton.getBoundingClientRect();
  const pickerRect = picker.getBoundingClientRect();
  const left = Math.min(Math.max(8, rect.left), window.innerWidth - pickerRect.width - 8);
  const top = Math.min(Math.max(8, rect.bottom + 6), window.innerHeight - pickerRect.height - 8);
  picker.style.left = `${left}px`;
  picker.style.top = `${top}px`;
  ui.floatingColorPicker = picker;
}

function initMapDeviceListClosePicker() {
  if (ui.mapPickerCloseInitialized) return;
  ui.mapPickerCloseInitialized = true;
  document.addEventListener("click", (e) => {
    if (e.target.closest(".map-device-palette-btn") || e.target.closest(".map-color-picker")) return;
    closeFloatingColorPicker();
  });
}

function connectPositionStream() {
  if (ui.positionEventSource) {
    ui.positionEventSource.close();
    ui.positionEventSource = null;
  }
  if (ui.sseReconnectTimer) {
    clearTimeout(ui.sseReconnectTimer);
    ui.sseReconnectTimer = null;
  }
  const es = new EventSource("/api/stream/positions");
  ui.positionEventSource = es;
  es.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "position") {
        refreshMapData({ preserveView: true });
      }
    } catch (_e) {
      /* ignore */
    }
  };
  es.onerror = () => {
    es.close();
    ui.positionEventSource = null;
    ui.sseReconnectTimer = setTimeout(() => {
      connectPositionStream();
    }, 4000);
  };
}

function renderMapDeviceList() {
  const host = document.getElementById("map-device-list");
  if (!host) return;
  host.innerHTML = "";
  if (state.devices.length === 0) {
    const empty = document.createElement("p");
    empty.className = "map-device-list-empty";
    empty.textContent = t("map.noDevices");
    host.appendChild(empty);
    return;
  }
  state.devices.forEach((device) => {
    const wrap = document.createElement("div");
    wrap.className = "map-device-row-wrap";
    const visible = state.visibleDeviceIds.has(device.id);
    wrap.classList.toggle("map-device-row-wrap--off", !visible);

    const row = document.createElement("div");
    row.className = "map-device-row";
    row.tabIndex = 0;
    row.setAttribute("role", "button");

    const colorIdx = Number(device.map_color_index) % MAP_COLOR_COUNT;
    const colorDot = document.createElement("span");
    colorDot.className = `map-device-color-dot map-color-swatch--${colorIdx}`;
    colorDot.setAttribute("aria-hidden", "true");

    const label = document.createElement("div");
    label.className = "map-device-row-label";
    label.textContent = device.name;
    const paletteBtn = document.createElement("button");
    paletteBtn.type = "button";
    paletteBtn.className = "map-device-palette-btn";
    paletteBtn.setAttribute("aria-label", t("map.chooseColor"));
    paletteBtn.innerHTML = '<span class="material-symbols-outlined" aria-hidden="true">palette</span>';
    paletteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const pickerOpenForDevice = ui.floatingColorPicker?.dataset.deviceId === device.id;
      if (pickerOpenForDevice) closeFloatingColorPicker();
      else openFloatingColorPicker(paletteBtn, device, colorIdx);
    });

    const onRowActivate = () => {
      toggleDeviceVisibility(device.id);
      renderMapDeviceList();
      refreshMapData({ preserveView: true });
    };
    row.addEventListener("click", (e) => {
      if (e.target.closest(".map-device-palette-btn") || e.target.closest(".map-color-picker")) return;
      onRowActivate();
    });
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onRowActivate();
      }
    });

    row.append(colorDot, label, paletteBtn);
    wrap.append(row);
    host.appendChild(wrap);
  });
}

function isMobileMapLayout() {
  return window.matchMedia("(max-width: 899px)").matches;
}

function setMapSidebarDrawerOpen(open) {
  const layout = ui.mapLayoutEl;
  const toggle = ui.mapSidebarToggleEl;
  if (!layout || !toggle) return;
  ui.mapSidebarDrawerOpen = !!open;
  layout.classList.toggle("map-layout--drawer-open", !!open);
  toggle.classList.toggle("is-active", !!open);
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.setAttribute("aria-label", open ? t("map.menuClose") : t("map.menuOpen"));
  if (ui.mapDrawerBackdropEl) {
    const showBackdrop = !!open && isMobileMapLayout();
    ui.mapDrawerBackdropEl.classList.toggle("is-open", showBackdrop);
    ui.mapDrawerBackdropEl.setAttribute("aria-hidden", showBackdrop ? "false" : "true");
  }
  if (ui.map) setTimeout(() => ui.map.invalidateSize(), 280);
}

function closeMapSidebarDrawer() {
  setMapSidebarDrawerOpen(false);
}

function collectVisibleMapLatLng() {
  const points = [];
  ui.routePointMarkers.forEach((marker) => {
    if (ui.map?.hasLayer(marker)) points.push(marker.getLatLng());
  });
  ui.markers.forEach((marker) => {
    if (ui.map?.hasLayer(marker)) points.push(marker.getLatLng());
  });
  ui.routeLines.forEach((line) => {
    if (!ui.map?.hasLayer(line)) return;
    const latLngs = line.getLatLngs();
    if (!Array.isArray(latLngs)) return;
    latLngs.forEach((latLng) => {
      if (latLng?.lat != null && latLng?.lng != null) points.push(latLng);
    });
  });
  return points;
}

function zoomMapToVisiblePoints() {
  if (!ui.map) return;
  const points = collectVisibleMapLatLng();
  if (!points.length) {
    pushToast(ui.toastArea, t("map.fit.noVisiblePoints"), "error");
    return;
  }
  const bounds = L.latLngBounds(points);
  if (!bounds.isValid()) return;
  ui.map.fitBounds(bounds, {
    padding: [24, 24],
    maxZoom: 18,
    animate: true,
    duration: 0.35,
  });
}

function initMapFitControl() {
  if (!ui.map) return;
  if (ui.mapFitControl) {
    ui.map.removeControl(ui.mapFitControl);
    ui.mapFitControl = null;
  }
  const FitControl = L.Control.extend({
    onAdd() {
      const container = L.DomUtil.create("div", "leaflet-bar leaflet-control leaflet-control-zoom-fit");
      const btn = L.DomUtil.create("button", "leaflet-control-zoom-fit-btn", container);
      btn.type = "button";
      btn.setAttribute("aria-label", t("map.fit.title"));
      btn.title = t("map.fit.title");
      btn.innerHTML = '<span class="material-symbols-outlined" aria-hidden="true">crop_free</span>';
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.disableScrollPropagation(container);
      L.DomEvent.on(btn, "click", (event) => {
        L.DomEvent.stop(event);
        zoomMapToVisiblePoints();
      });
      return container;
    },
  });
  ui.mapFitControl = new FitControl({ position: "topleft" });
  ui.map.addControl(ui.mapFitControl);
}

function toggleMapSidebarDrawer() {
  const layout = ui.mapLayoutEl;
  if (!layout) return;
  setMapSidebarDrawerOpen(!layout.classList.contains("map-layout--drawer-open"));
}

function initMapSidebarDrawer() {
  const toggle = document.getElementById("map-sidebar-toggle");
  ui.mapSidebarToggleEl = toggle;
  ui.mapLayoutEl = document.querySelector(".map-layout");
  ui.mapDrawerBackdropEl = document.querySelector(".map-drawer-backdrop");
  const pageMap = document.getElementById("page-map");
  if (!ui.mapSidebarListenersBound) {
    ui.mapSidebarListenersBound = true;
    toggle?.addEventListener("click", () => toggleMapSidebarDrawer());
  }
  if (!ui.mapSidebarDelegatedClick && pageMap) {
    ui.mapSidebarDelegatedClick = true;
    pageMap.addEventListener("click", (e) => {
      const t = e.target;
      if (t instanceof Element && t.classList.contains("map-drawer-backdrop")) {
        closeMapSidebarDrawer();
      }
    });
  }
  const mq = window.matchMedia("(min-width: 900px)");
  const sync = () => {
    ui.mapLayoutEl = document.querySelector(".map-layout");
    ui.mapDrawerBackdropEl = document.querySelector(".map-drawer-backdrop");
    const isDesktop = mq.matches;
    const changedViewportMode = ui.mapSidebarDesktopMode === null || ui.mapSidebarDesktopMode !== isDesktop;
    ui.mapSidebarDesktopMode = isDesktop;
    if (changedViewportMode) {
      setMapSidebarDrawerOpen(isDesktop);
    } else if (typeof ui.mapSidebarDrawerOpen === "boolean") {
      setMapSidebarDrawerOpen(ui.mapSidebarDrawerOpen);
    }
    if (isDesktop) {
      ui.mapDrawerBackdropEl?.classList.remove("is-open");
      ui.mapDrawerBackdropEl?.setAttribute("aria-hidden", "true");
    } else if (ui.mapDrawerBackdropEl && !ui.mapLayoutEl?.classList.contains("map-layout--drawer-open")) {
      ui.mapDrawerBackdropEl.classList.remove("is-open");
      ui.mapDrawerBackdropEl.setAttribute("aria-hidden", "true");
    }
    if (ui.map) setTimeout(() => ui.map.invalidateSize(), 150);
  };
  if (!ui.mapSidebarMqBound) {
    ui.mapSidebarMqBound = true;
    mq.addEventListener("change", sync);
  }
  sync();
}

function initSettingsHashRouting() {
  const onHash = (ev) => {
    if (location.hash === SETTINGS_HASH) {
      openSettingsModalUiOnly();
      return;
    }
    if (!ui.settingsModalOpen) return;
    let oldHash = "";
    try {
      if (typeof ev?.oldURL === "string" && ev.oldURL) {
        oldHash = new URL(ev.oldURL).hash;
      }
    } catch {
      oldHash = "";
    }
    const leftSettingsRoute = oldHash === SETTINGS_HASH || oldHash === "";
    if (ui.settingsDirty && leftSettingsRoute) {
      const restore =
        typeof ev?.oldURL === "string" && ev.oldURL
          ? ev.oldURL
          : `${window.location.pathname}${window.location.search}${SETTINGS_HASH}`;
      history.replaceState(null, "", restore);
      queueMicrotask(() => {
        if (!ui.settingsUnsavedDialogOpen) {
          openUnsavedSettingsCloseConfirm(() => dismissSettingsRoute());
        }
      });
      return;
    }
    closeSettingsModalUiOnly();
  };
  window.addEventListener("hashchange", onHash);
  if (location.hash === SETTINGS_HASH) {
    openSettingsModalUiOnly();
  }
}

function openSettingsModalUiOnly() {
  const page = document.getElementById("page-settings");
  if (!page) return;
  const wasActive = page.classList.contains("active");
  page.classList.add("active");
  ui.settingsModalOpen = true;
  if (!ui.settingsEscKeyListener) {
    ui.settingsEscKeyListener = (event) => {
      if (event.key !== "Escape" || !ui.settingsModalOpen || ui.settingsUnsavedDialogOpen) return;
      if (document.querySelector(".modal-overlay.modal-overlay--shown")) return;
      event.preventDefault();
      closeSettingsModal();
    };
    document.addEventListener("keydown", ui.settingsEscKeyListener);
  }
  if (!wasActive) {
    page.classList.remove("settings-modal--shown");
    requestAnimationFrame(() => {
      requestAnimationFrame(() => page.classList.add("settings-modal--shown"));
    });
  } else if (!page.classList.contains("settings-modal--shown")) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => page.classList.add("settings-modal--shown"));
    });
  }
}

function closeSettingsModalUiOnly() {
  const page = document.getElementById("page-settings");
  if (!page || !ui.settingsModalOpen) return;
  const finish = () => {
    page.classList.remove("active", "settings-modal--shown");
    ui.settingsModalOpen = false;
    if (ui.settingsEscKeyListener) {
      document.removeEventListener("keydown", ui.settingsEscKeyListener);
      ui.settingsEscKeyListener = null;
    }
  };
  if (page.classList.contains("settings-modal--shown")) {
    page.classList.remove("settings-modal--shown");
    window.setTimeout(finish, readModalAnimationDurationMs() + 40);
  } else {
    finish();
  }
}

function dismissSettingsRoute() {
  if (location.hash === SETTINGS_HASH) {
    if (window.history.length > 1) {
      history.back();
    } else {
      history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      closeSettingsModalUiOnly();
    }
  } else {
    closeSettingsModalUiOnly();
  }
}

async function persistMainSettingsFromUi() {
  const refs = ui.settingsFormRefs;
  if (!refs?.nasInterval || !refs?.nasPath || !refs?.themeSelect) {
    throw new Error(t("settings.notLoaded"));
  }
  const { nasInterval, nasPath, themeSelect } = refs;
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
  pushToast(ui.toastArea, t("settings.saved"), "success");
  ui.settingsDirty = false;
}

async function discardSettingsAndClose() {
  try {
    await loadSettings();
    applyTheme(state.settings.theme || "light");
    buildSettingsPage();
    ui.settingsDirty = false;
    dismissSettingsRoute();
  } catch (err) {
    pushToast(ui.toastArea, err.message, "error");
  }
}

function openUnsavedSettingsCloseConfirm(afterResolved) {
  if (ui.settingsUnsavedDialogOpen) return;
  ui.settingsUnsavedDialogOpen = true;
  const message = document.createElement("div");
  message.textContent = t("settings.unsaved.message");
  const discardBtn = createButton({ label: t("settings.unsaved.discard") });
  discardBtn.classList.add("btn-secondary");
  const saveBtn = createButton({ label: t("common.save"), icon: "check" });
  saveBtn.classList.add("btn-primary");
  const modal = createModal({
    title: t("settings.unsaved.title"),
    content: message,
    actions: [discardBtn, saveBtn],
    closeOnBackdrop: false,
    closeOnEscape: false,
  });
  discardBtn.addEventListener("click", async () => {
    try {
      await loadSettings();
      applyTheme(state.settings.theme || "light");
      buildSettingsPage();
      ui.settingsDirty = false;
      ui.settingsUnsavedDialogOpen = false;
      modal.close();
      afterResolved?.();
    } catch (err) {
      pushToast(ui.toastArea, err.message, "error");
      ui.settingsUnsavedDialogOpen = false;
      modal.close();
    }
  });
  saveBtn.addEventListener("click", async () => {
    setButtonLoading(saveBtn, true, t("common.saving"));
    try {
      await persistMainSettingsFromUi();
      ui.settingsUnsavedDialogOpen = false;
      modal.close();
      afterResolved?.();
    } catch (err) {
      pushToast(ui.toastArea, err.message, "error");
    } finally {
      setButtonLoading(saveBtn, false);
    }
  });
  modal.open();
}

function openSettingsModal() {
  if (location.hash === SETTINGS_HASH) {
    openSettingsModalUiOnly();
  } else {
    location.hash = SETTINGS_HASH;
  }
}

function closeSettingsModal() {
  if (!ui.settingsModalOpen) return;
  if (ui.settingsDirty) {
    openUnsavedSettingsCloseConfirm(() => dismissSettingsRoute());
    return;
  }
  dismissSettingsRoute();
}

function buildMapPage() {
  const page = document.getElementById("page-map");
  page.classList.add("active");
  page.innerHTML = `<div class="map-layout"><div class="map-drawer-backdrop" aria-hidden="true"></div><div class="card ui-panel map-filters-panel"><div id="map-filters" class="ui-form-grid"></div></div><div class="map-wrap ui-map-wrap"><div id="map"></div><div class="map-overlay ui-overlay-panel" id="map-overlay"></div></div></div>`;

  ui.mapLayoutEl = page.querySelector(".map-layout");
  ui.mapDrawerBackdropEl = page.querySelector(".map-drawer-backdrop");

  const filtersHost = page.querySelector("#map-filters");
  const deviceListHost = document.createElement("div");
  deviceListHost.className = "field";
  const deviceListLabel = document.createElement("span");
  deviceListLabel.id = "map-device-list-label";
  deviceListLabel.className = "field-label-text";
  deviceListLabel.textContent = t("settings.devices.title");
  const deviceList = document.createElement("div");
  deviceList.id = "map-device-list";
  deviceList.className = "map-device-list";
  deviceList.setAttribute("role", "group");
  deviceList.setAttribute("aria-label", t("map.devices.toggleAria"));
  deviceListHost.append(deviceListLabel, deviceList);
  const rangeField = document.createElement("div");
  rangeField.className = "field";
  const rangeLabel = document.createElement("span");
  rangeLabel.id = "map-range-label";
  rangeLabel.className = "field-label-text";
  rangeLabel.textContent = t("map.range.title");
  const rangePicker = document.createElement("div");
  rangePicker.id = "map-range-picker";
  rangePicker.className = "segmented map-range-picker";
  const ranges = [
    { value: MAP_RANGE_CURRENT, label: t("map.range.current") },
    { value: "1h", label: t("map.range.last1h") },
    { value: "6h", label: t("map.range.last6h") },
    { value: "24h", label: t("map.range.last24h") },
    { value: "7d", label: t("map.range.last7d") },
    { value: "30d", label: t("map.range.last30d") },
    { value: "custom", label: t("map.range.custom") },
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
      setSelectedRangeCountStatus({ loading: true, count: null });
      refreshMapData({ fromField, toField });
      if (isMobileMapLayout()) closeMapSidebarDrawer();
    });
    rangePicker.append(input, label);
  });
  rangeField.append(rangeLabel, rangePicker);
  const customDateWrap = document.createElement("div");
  customDateWrap.className = "map-custom-dates";
  const fromField = createField({ label: t("map.range.fromDate"), type: "date" });
  fromField.input.id = "map-from";
  fromField.input.value = localStorage.getItem("gpslogger.map.fromDate") || "";
  const toField = createField({ label: t("map.range.toDate"), type: "date" });
  toField.input.id = "map-to";
  toField.input.value = localStorage.getItem("gpslogger.map.toDate") || "";
  customDateWrap.append(fromField.field, toField.field);
  customDateWrap.hidden = ui.mapRange !== "custom";
  const footer = document.createElement("div");
  footer.className = "map-filters-footer";
  const statusBtn = createButton({
    label: t("status.title"),
    icon: "monitoring",
    onClick: () => {
      if (isMobileMapLayout()) closeMapSidebarDrawer();
      openStatusModal();
    },
  });
  statusBtn.id = "map-status-btn";
  statusBtn.classList.add("btn-secondary", "map-settings-btn");
  const settingsBtn = createButton({
    label: t("settings.title"),
    icon: "settings",
    onClick: () => {
      if (isMobileMapLayout()) closeMapSidebarDrawer();
      openSettingsModal();
    },
  });
  settingsBtn.id = "map-settings-btn";
  settingsBtn.classList.add("btn-secondary", "map-settings-btn");
  footer.append(statusBtn, settingsBtn);
  filtersHost.append(deviceListHost, rangeField, customDateWrap, footer);

  initMapDeviceListClosePicker();
  renderMapDeviceList();
  fromField.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && ui.mapRange === "custom") {
      refreshMapData({ fromField, toField });
    }
  });
  toField.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && ui.mapRange === "custom") {
      refreshMapData({ fromField, toField });
    }
  });
  fromField.input.addEventListener("change", () => {
    localStorage.setItem("gpslogger.map.fromDate", fromField.input.value || "");
    if (ui.mapRange === "custom") refreshMapData({ fromField, toField });
  });
  toField.input.addEventListener("change", () => {
    localStorage.setItem("gpslogger.map.toDate", toField.input.value || "");
    if (ui.mapRange === "custom") refreshMapData({ fromField, toField });
  });

  ui.map = L.map("map", {
    zoomControl: true,
    scrollWheelZoom: true,
    touchZoom: true,
    attributionControl: false,
  }).setView([51.2, 10.4], 6);
  initMapFitControl();
  ui.map.on("click", () => closePinnedRouteTooltip());
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest(".leaflet-interactive.map-route-point") || target.closest(".leaflet-tooltip")) return;
    closePinnedRouteTooltip();
  });
  ui.layers.street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "",
    maxZoom: 19,
  });
  ui.layers.satellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "", maxZoom: 19 },
  );
  if (ui.mapMode === "satellite") {
    ui.layers.satellite.addTo(ui.map);
  } else {
    ui.layers.street.addTo(ui.map);
  }

  const overlay = page.querySelector("#map-overlay");
  const layerSwitch = createSwitch({
    label: t("map.satellite"),
    value: ui.mapMode === "satellite",
    onChange: (enabled) => setMapMode(enabled ? "satellite" : "street"),
  });
  layerSwitch.wrap.classList.add("ui-map-toggle");
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
  setSelectedRangeCountStatus({ loading: true, count: null });
  if (ui.mapRange === MAP_RANGE_CURRENT) {
    if (opts.reloadBtn) {
      setButtonLoading(opts.reloadBtn, true, "Lädt...");
    }
    try {
      const renderedCount = await drawCurrentPositionsOnly({ preserveView: !!opts.preserveView });
      setSelectedRangeCountStatus({ loading: false, count: renderedCount });
    } catch (err) {
      setSelectedRangeCountStatus({ loading: false, count: null });
      pushToast(ui.toastArea, err.message, "error");
    } finally {
      if (opts.reloadBtn) {
        setButtonLoading(opts.reloadBtn, false);
      }
    }
    return;
  }
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
    setSelectedRangeCountStatus({ loading: false, count: null });
    return;
  }

  if (opts.reloadBtn) {
    setButtonLoading(opts.reloadBtn, true, "Lädt...");
  }
  const query = new URLSearchParams();
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  try {
    const positions = await loadAllPositionsForRange(query);
    setFieldState(fromField, "success", "");
    setFieldState(toField, "success", "");
    const renderedCount = drawPositions(positions, { preserveView: !!opts.preserveView });
    setSelectedRangeCountStatus({ loading: false, count: renderedCount });
  } catch (err) {
    setSelectedRangeCountStatus({ loading: false, count: null });
    pushToast(ui.toastArea, err.message, "error");
  } finally {
    if (opts.reloadBtn) {
      setButtonLoading(opts.reloadBtn, false);
    }
  }
}

const POSITIONS_PAGE_SIZE = 500;
const POSITIONS_MAX_PAGES = 200;

function formatPositionCountLabel(count) {
  const safeCount = Number.isFinite(Number(count)) ? Math.max(0, Number(count)) : 0;
  return `${safeCount} ${safeCount === 1 ? "Position" : "Positionen"}`;
}

function setSelectedRangeCountStatus({ loading = false, count = null } = {}) {
  const rangePicker = document.getElementById("map-range-picker");
  if (!rangePicker) return;
  const labels = rangePicker.querySelectorAll("label");
  labels.forEach((label) => {
    label.classList.remove("is-loading");
    const badge = label.querySelector(".map-range-count");
    if (badge) badge.remove();
  });
  const selectedInput = rangePicker.querySelector('input[name="map-range"]:checked');
  if (!selectedInput) return;
  const selectedLabel = rangePicker.querySelector(`label[for="${selectedInput.id}"]`);
  if (!selectedLabel) return;
  if (!loading && count == null) return;
  const badge = document.createElement("span");
  badge.className = "map-range-count";
  if (loading) {
    badge.textContent = "Lädt...";
    selectedLabel.classList.add("is-loading");
  } else {
    badge.textContent = formatPositionCountLabel(count);
  }
  selectedLabel.appendChild(badge);
}

function buildPositionDedupKey(pos) {
  return [
    pos.device_id ?? "",
    pos.timestamp ?? "",
    pos.latitude ?? "",
    pos.longitude ?? "",
    pos.accuracy ?? "",
  ].join("|");
}

function normalizeAndSortPositions(positions) {
  const seen = new Set();
  const merged = [];
  positions.forEach((pos) => {
    const key = buildPositionDedupKey(pos);
    if (seen.has(key)) return;
    seen.add(key);
    merged.push(pos);
  });
  merged.sort((a, b) => {
    const tA = Date.parse(String(a?.timestamp ?? ""));
    const tB = Date.parse(String(b?.timestamp ?? ""));
    if (Number.isFinite(tA) && Number.isFinite(tB) && tA !== tB) return tA - tB;
    return String(a?.timestamp ?? "").localeCompare(String(b?.timestamp ?? ""));
  });
  return merged;
}

async function loadAllPositionsForRange(baseQuery) {
  const allPositions = [];
  let offset = 0;
  let hasMore = true;
  let pages = 0;
  while (hasMore) {
    pages += 1;
    if (pages > POSITIONS_MAX_PAGES) {
      throw new Error("Zu viele Positionsseiten geladen. Bitte Zeitraum eingrenzen.");
    }
    const pageQuery = new URLSearchParams(baseQuery.toString());
    pageQuery.set("limit", String(POSITIONS_PAGE_SIZE));
    pageQuery.set("offset", String(offset));
    const data = await api(`/api/positions?${pageQuery.toString()}`);
    const positions = Array.isArray(data?.positions) ? data.positions : [];
    allPositions.push(...positions);
    const pagination = data?.pagination || {};
    hasMore = Boolean(pagination.has_more);
    const returned = Number(pagination.returned ?? positions.length);
    if (!Number.isFinite(returned) || returned < 0) {
      throw new Error("Ungültige Pagination-Antwort vom Server.");
    }
    if (hasMore && returned === 0) {
      throw new Error("Pagination konnte nicht fortgesetzt werden (0 Elemente mit has_more=true).");
    }
    offset += returned;
  }
  return normalizeAndSortPositions(allPositions);
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

function isCustomRangeInPast() {
  if (ui.mapRange !== "custom") return false;
  const toInput = document.getElementById("map-to");
  const toValue = toInput?.value || "";
  if (!toValue) return false;
  const toDateEnd = new Date(`${toValue}T23:59:59.999`);
  if (Number.isNaN(toDateEnd.getTime())) return false;
  return toDateEnd.getTime() < Date.now();
}

function isCurrentPoint(deviceId, latestTs) {
  const status = state.deviceStatuses[deviceId];
  if (!status?.last_seen || !latestTs) return false;
  return String(status.last_seen) === String(latestTs);
}

function drawPositions(positions, opts = {}) {
  const preserveView = !!opts.preserveView;
  clearMapOverlays();
  const visible = state.visibleDeviceIds;
  const filtered = positions.filter((p) => p.device_id && visible.has(p.device_id));
  if (!filtered.length) return 0;

  const byDevice = new Map();
  filtered.forEach((p) => {
    if (!byDevice.has(p.device_id)) byDevice.set(p.device_id, []);
    byDevice.get(p.device_id).push(p);
  });

  const allLatLng = [];
  const customPast = isCustomRangeInPast();
  byDevice.forEach((items, deviceId) => {
    items.sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
    const route = items.map((item) => [item.latitude, item.longitude]);
    allLatLng.push(...route);
    const colorIdx = getDeviceColorIndex(deviceId);
    const stroke = resolvePaletteColor(colorIdx);
    const line = L.polyline(route, {
      color: stroke,
      weight: getMapCssNumber("--map-route-line-width", 3),
      opacity: getMapCssNumber("--map-route-line-opacity", 0.9),
    }).addTo(ui.map);
    ui.routeLines.push(line);

    const latest = items[items.length - 1];
    const shouldTreatLatestAsLive = !customPast && isCurrentPoint(deviceId, latest?.timestamp);
    const pointsToRender = shouldTreatLatestAsLive ? items.slice(0, -1) : items;
    pointsToRender.forEach((point) => {
      const routePoint = L.circleMarker([point.latitude, point.longitude], {
        radius: getMapCssNumber("--map-route-point-radius", 3),
        fillColor: getMapCssVar("--map-route-point-fill"),
        color: getMapCssVar("--map-route-point-stroke"),
        weight: getMapCssNumber("--map-route-point-stroke-width", 1),
        fillOpacity: getMapCssNumber("--map-route-point-fill-opacity", 1),
        opacity: getMapCssNumber("--map-route-point-stroke-opacity", 1),
        className: "map-route-point",
      }).addTo(ui.map);
      routePoint.bindTooltip(buildPositionTooltipHtml(point), {
        sticky: true,
        className: "map-point-tooltip",
      });
      bindRoutePointInteractions(routePoint);
      ui.routePointMarkers.push(routePoint);
    });

    if (!shouldTreatLatestAsLive) return;
    const marker = L.circleMarker([latest.latitude, latest.longitude], {
      radius: getMapCssNumber("--map-live-point-radius", 7),
      fillColor: stroke,
      color: getMapCssVar("--map-live-point-border"),
      weight: getMapCssNumber("--map-live-point-border-width", 2),
      fillOpacity: getMapCssNumber("--map-live-point-fill-opacity", 1),
      opacity: getMapCssNumber("--map-live-point-stroke-opacity", 1),
      className: "map-live-point map-live-point--pulse",
    });
    marker.bindTooltip(escapeHtml(formatRelativeTime(latest.timestamp)), {
      permanent: true,
      direction: "top",
      offset: [0, -24],
      className: "map-live-age-tooltip",
    });
    marker.bindPopup(buildPositionTooltipHtml(latest), {
      className: "map-point-tooltip map-point-tooltip--live",
    });
    marker.addTo(ui.map);
    addLivePointInitialMarker([latest.latitude, latest.longitude], getDeviceDisplayName(latest.device_id, latest.device_name));
    ui.markers.set(latest.device_id, marker);
  });

  if (!preserveView) {
    const bounds = L.latLngBounds(allLatLng);
    if (bounds.isValid()) ui.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 18 });
  }
  return filtered.length;
}

function renderDevicesSection() {
  const createHost = document.getElementById("devices-add-host");
  const listHost = document.getElementById("devices-list");
  if (!createHost || !listHost) return;
  createHost.innerHTML = "";
  const addBtn = createButton({
    label: t("settings.devices.add"),
    icon: "add",
    onClick: () => openDeviceEditorModal(),
  });
  addBtn.id = "settings-add-device-btn";
  addBtn.setAttribute("aria-label", t("settings.devices.add"));
  addBtn.classList.add("btn-primary", "settings-form-button");
  createHost.appendChild(addBtn);
  renderDeviceList();
}

async function openDeviceEditorModal(device = null) {
  const isEdit = !!device;
  let draft = null;
  if (!isEdit) {
    try {
      draft = await api("/api/devices/draft", { method: "POST", body: JSON.stringify({}) });
    } catch (err) {
      pushToast(ui.toastArea, err.message, "error");
      return;
    }
  }
  const content = document.createElement("div");
  const nameField = createField({
    label: "Name",
    placeholder: "z. B. Caspar",
    value: isEdit ? String(device.name || "") : "",
  });
  const keyField = createField({
    label: "API-Key (Vorschlag editierbar, z. B. kürzerer Key; min. 8 Zeichen, keine Leerzeichen)",
    value: isEdit ? String(device.api_key || "") : String(draft.api_key || ""),
    placeholder: "Key anpassen oder Vorschlag belassen",
  });
  content.append(nameField.field, keyField.field);
  const cancelBtn = createButton({ label: "Abbrechen" });
  const saveBtn = createButton({ label: "Speichern", icon: "check" });
  saveBtn.classList.add("btn-primary");
  const modal = createModal({
    title: isEdit ? "Gerät bearbeiten" : "Gerät hinzufügen",
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
      if (isEdit) {
        await api(`/api/devices/${device.id}`, {
          method: "PUT",
          body: JSON.stringify({
            name,
            api_key: keyField.input.value.trim() || undefined,
          }),
        });
      } else {
        await api("/api/devices/commit", {
          method: "POST",
          body: JSON.stringify({
            draft_token: draft.draft_token,
            name,
            api_key: keyField.input.value.trim() || undefined,
          }),
        });
      }
      await loadDevices();
      await loadDeviceStatuses();
      renderDeviceList();
      renderMapDeviceList();
      pushToast(ui.toastArea, isEdit ? "Gerät aktualisiert" : "Gerät angelegt", "success");
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
    item.className = "list-item list-item-managed";
    const leading = document.createElement("div");
    leading.className = "list-item-leading list-item-leading-icon";
    leading.innerHTML = '<span class="material-symbols-outlined" aria-hidden="true">sensors</span>';
    const info = document.createElement("div");
    const status = state.deviceStatuses[device.id];
    const seen = status?.last_seen ? new Date(status.last_seen).toLocaleString(currentLanguage === "de" ? "de-DE" : "en-US") : t("devices.never");
    const position =
      status?.latitude != null && status?.longitude != null
        ? `${Number(status.latitude).toFixed(5)}, ${Number(status.longitude).toFixed(5)}`
        : t("devices.noPosition");
    const statBits = [];
    if (status?.battery != null && status.battery !== "") statBits.push(`${t("devices.battery")}: ${status.battery}`);
    if (status?.speed != null) statBits.push(`${t("devices.speed")}: ${status.speed}`);
    if (status?.provider) statBits.push(String(status.provider));
    if (status?.activity) statBits.push(String(status.activity));
    const statExtra = statBits.length
      ? `<br><small>${statBits.map((t) => escapeHtml(t)).join(" · ")}</small>`
      : "";
    info.innerHTML = `<strong>${escapeHtml(device.name)}</strong><br><small>${escapeHtml(t("devices.lastSeen"))}: ${escapeHtml(seen)}</small><br><small>${escapeHtml(t("devices.position"))}: ${escapeHtml(position)}</small>${statExtra}`;
    const actions = document.createElement("div");
    actions.className = "ui-item-actions";
    const copyKeyBtn = createIconButton({
      icon: "content_copy",
      title: "Key kopieren",
      onClick: async () => {
        try {
          await navigator.clipboard.writeText(device.api_key || "");
          pushToast(ui.toastArea, "API-Key kopiert", "success");
        } catch (_err) {
          pushToast(ui.toastArea, "Kopieren nicht möglich", "error");
        }
      },
    });
    copyKeyBtn.setAttribute("aria-label", "Key kopieren");
    const editBtn = createIconButton({
      icon: "edit",
      title: "Gerät bearbeiten",
      onClick: async () => {
        openDeviceEditorModal(device);
      },
    });
    editBtn.setAttribute("aria-label", `Gerät ${device.name} bearbeiten`);
    const deleteBtn = createIconButton({
      icon: "delete",
      title: "Löschen",
      onClick: async () => {
        openDeleteModal(device);
      },
    });
    deleteBtn.setAttribute("aria-label", `Gerät ${device.name} löschen`);
    deleteBtn.classList.add("btn-danger");
    actions.append(copyKeyBtn, editBtn, deleteBtn);
    item.append(leading, info, actions);
    list.appendChild(item);
  });
}

function showApiKeyModal(device) {
  const keyField = createField({ label: `${device.name} API-Key`, value: device.api_key });
  keyField.input.readOnly = true;
  const copyBtn = createIconButton({
    icon: "content_copy",
    title: "Key kopieren",
    onClick: async () => {
      try {
        await navigator.clipboard.writeText(device.api_key);
        pushToast(ui.toastArea, "API-Key kopiert", "success");
      } catch (_err) {
        pushToast(ui.toastArea, "Kopieren nicht möglich", "error");
      }
    },
  });
  copyBtn.setAttribute("aria-label", "Key kopieren");
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
        renderMapDeviceList();
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
        renderMapDeviceList();
        await refreshMapData({ preserveView: true });
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
  page.classList.remove("active", "settings-modal--shown");
  page.classList.add("settings-modal");
  page.innerHTML = `
    <div class="settings-modal-backdrop" data-action="close-settings"></div>
    <div class="card settings-card settings-modal-card">
      <div class="settings-modal-head">
        <h2><span class="material-symbols-outlined" aria-hidden="true">settings</span><span id="settings-title-text">${t("settings.title")}</span></h2>
        <button type="button" class="icon-btn settings-modal-close" data-action="close-settings" aria-label="${t("settings.close")}">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>
      <div class="settings-modal-body">
      <section class="settings-section">
        <h3 id="settings-system-title">${t("settings.system.title")}</h3>
        <div id="settings-system" class="ui-form-grid"></div>
      </section>
      <section class="settings-section">
        <h3 id="settings-storage-title">${t("settings.storage.title")}</h3>
        <div id="settings-storage" class="ui-form-grid"></div>
      </section>
      <section class="settings-section">
        <div class="ui-form-grid">
          <span id="settings-forwardings-label" class="settings-row-label">${t("settings.forwardings.title")}</span>
          <div id="settings-forwarding" class="settings-list-field">
            <div id="forwardings-list" class="list ui-list"></div>
            <div id="forwarding-add-host" class="settings-list-actions"></div>
            <div id="forwarding-test-result" class="forwarding-test-result" hidden></div>
          </div>
        </div>
      </section>
      <section class="settings-section">
        <div class="ui-form-grid">
          <span id="settings-devices-label" class="settings-row-label">${t("settings.devices.title")}</span>
          <div class="settings-list-field">
            <div id="devices-list" class="list ui-list"></div>
            <div id="devices-add-host" class="settings-list-actions"></div>
          </div>
        </div>
      </section>
      <section class="settings-section settings-actions-section">
        <div id="settings-actions" class="ui-form-grid"></div>
      </section>
      </div>
      <div id="settings-save-footer" class="settings-save-footer"></div>
    </div>
  `;
  const closeBtn = page.querySelector(".settings-modal-close");
  closeBtn?.addEventListener("click", () => closeSettingsModal());
  const settingsBackdrop = page.querySelector(".settings-modal-backdrop");
  let backdropPointerDown = false;
  settingsBackdrop?.addEventListener("pointerdown", (event) => {
    backdropPointerDown = event.target === settingsBackdrop;
  });
  settingsBackdrop?.addEventListener("click", (event) => {
    if (event.target !== settingsBackdrop || !backdropPointerDown) return;
    closeSettingsModal();
  });
  const systemHost = page.querySelector("#settings-system");
  const storageHost = page.querySelector("#settings-storage");
  const forwardingAddHost = page.querySelector("#forwarding-add-host");

  const nasInterval = createField({
    label: t("settings.storage.nasInterval"),
    type: "number",
    value: String(state.settings.nas_interval_seconds || 60),
  });
  const nasPath = createField({ label: t("settings.storage.nasPath"), value: state.settings.nas_path || "nas_storage" });
  const themeSelect = createField({ label: t("settings.system.theme"), type: "select" });
  themeSelect.input.innerHTML = state.themes.map((name) => `<option value="${name}">${name}</option>`).join("");
  themeSelect.input.value = state.settings.theme || "light";
  const languageSelect = createField({ label: t("settings.system.language"), type: "select" });
  languageSelect.input.innerHTML = SUPPORTED_LANGUAGES.map((lang) => `<option value="${lang}">${t(`language.${lang}`)}</option>`).join("");
  languageSelect.input.value = currentLanguage;

  const saveNowBtn = createButton({
    label: t("settings.storage.saveNow"),
    icon: "save",
    onClick: async () => {
      setButtonLoading(saveNowBtn, true, t("common.saving"));
      try {
        const res = await api("/api/save-now", { method: "POST" });
        pushToast(ui.toastArea, t("settings.storage.savedCount", { count: res.result.saved_count }), "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
      } finally {
        setButtonLoading(saveNowBtn, false);
      }
    },
  });
  saveNowBtn.classList.add("btn-secondary", "settings-form-button");
  saveNowBtn.id = "settings-save-now-btn";

  const saveBtn = createButton({
    label: t("settings.save"),
    icon: "check",
    onClick: async () => {
      setButtonLoading(saveBtn, true, t("common.saving"));
      try {
        await persistMainSettingsFromUi();
        dismissSettingsRoute();
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
      } finally {
        setButtonLoading(saveBtn, false);
      }
    },
  });
  saveBtn.classList.add("btn-primary", "btn-settings-save");
  saveBtn.id = "settings-save-btn";
  const cancelBtn = createButton({
    label: t("settings.cancel"),
    icon: "close",
    onClick: () => discardSettingsAndClose(),
  });
  cancelBtn.id = "settings-cancel-btn";
  cancelBtn.classList.add("btn-secondary");

  themeSelect.input.addEventListener("change", () => {
    applyTheme(themeSelect.input.value);
    ui.settingsDirty = true;
  });
  languageSelect.input.addEventListener("change", async () => {
    await loadLanguage(languageSelect.input.value);
    updateVisibleTexts();
    ui.settingsDirty = true;
  });
  nasInterval.input.addEventListener("input", () => {
    ui.settingsDirty = true;
  });
  nasPath.input.addEventListener("input", () => {
    ui.settingsDirty = true;
  });
  systemHost.append(themeSelect.field, languageSelect.field);
  storageHost.append(nasInterval.field, nasPath.field, saveNowBtn);
  const addFwBtn = createButton({
    label: t("settings.forwardings.add"),
    icon: "add",
    onClick: () => openForwardingModal(null),
  });
  addFwBtn.id = "settings-add-forwarding-btn";
  addFwBtn.setAttribute("aria-label", t("settings.forwardings.add"));
  addFwBtn.classList.add("btn-primary", "settings-form-button");
  forwardingAddHost?.appendChild(addFwBtn);
  renderForwardingList();
  const actionsHost = page.querySelector("#settings-actions");
  const actionsLabel = document.createElement("span");
  actionsLabel.className = "settings-action-label";
  actionsLabel.textContent = t("settings.actions.title");
  const restartBtn = createButton({
    label: t("settings.actions.restart"),
    icon: "refresh",
    onClick: () => runGpsloggerRestart(restartBtn),
  });
  restartBtn.id = "settings-restart-btn";
  restartBtn.classList.add("btn-secondary", "settings-form-button");
  actionsHost?.append(actionsLabel, restartBtn);
  const saveFooter = page.querySelector("#settings-save-footer");
  const footerActions = document.createElement("div");
  footerActions.className = "settings-footer-actions";
  footerActions.append(cancelBtn, saveBtn);
  saveFooter?.appendChild(footerActions);
  ui.settingsFormRefs = { nasInterval, nasPath, themeSelect, languageSelect, saveBtn };
  ui.settingsDirty = false;
  renderDevicesSection();
}

function renderForwardingTestResult() {
  const host = document.getElementById("forwarding-test-result");
  if (!host) return;
  const result = state.lastForwardingTestResult;
  if (!result) {
    host.hidden = true;
    host.innerHTML = "";
    return;
  }
  const attempts = [];
  (result.device_runs || []).forEach((run) => {
    (run.attempts || []).forEach((attempt) => {
      attempts.push({
        device_name: run.device_name || run.device_id || t("common.unknown"),
        used_source: run.used_source || "",
        ...attempt,
      });
    });
  });
  const attemptRows = attempts.length
    ? attempts
        .map((entry) => {
          const statusText = entry.ok
            ? `OK (${entry.http_status || "HTTP"})`
            : entry.http_status
              ? `Fehler (HTTP ${entry.http_status})`
              : t("status.forwardingTest.error");
          const stage = entry.stage || t("common.unknown");
          const err = entry.error ? escapeHtml(entry.error) : t("common.na");
          const excerpt = entry.response_excerpt ? `<small>${t("status.forwardingTest.response")}: ${escapeHtml(entry.response_excerpt)}</small>` : "";
          const method = escapeHtml(entry.request_method || "POST");
          const contentType = escapeHtml(entry.request_content_type || t("common.na"));
          const replayFlag = entry.replay_available ? t("common.yes") : t("common.no");
          const replayUsed = entry.replay_used ? t("common.yes") : t("common.no");
          const bodyUnchanged = entry.body_unchanged ? t("common.yes") : t("common.no");
          const bodySource = escapeHtml(entry.body_source || t("common.unknown"));
          const headerSource = escapeHtml(entry.header_source || t("common.unknown"));
          const originalRequestDevice = escapeHtml(entry.original_request_device || t("common.na"));
          const displayDeviceName = escapeHtml(entry.device_display_name || t("common.na"));
          const sentDeviceValue = escapeHtml(entry.sent_device_value || t("common.na"));
          const replayReason = entry.replay_reason ? `<small>${t("status.forwardingTest.replayHint")}: ${escapeHtml(entry.replay_reason)}</small>` : "";
          return `<div class="forwarding-test-row"><strong>${escapeHtml(entry.device_name)}</strong><small>${escapeHtml(statusText)} · ${t("status.forwardingTest.stage")}: ${escapeHtml(stage)} · ${t("status.forwardingTest.requestSent")}: ${entry.request_sent ? t("common.yes") : t("common.no")} · ${t("status.forwardingTest.source")}: ${escapeHtml(entry.used_source)}</small><small>${t("status.forwardingTest.target")}: ${escapeHtml(entry.target_url || t("common.na"))}</small><small>${t("status.forwardingTest.method")}: ${method} · ${t("status.forwardingTest.contentType")}: ${contentType}</small><small>${t("status.forwardingTest.bodySource")}: ${bodySource} · ${t("status.forwardingTest.headerSource")}: ${headerSource}</small><small>${t("status.forwardingTest.replayAvailable")}: ${replayFlag} · ${t("status.forwardingTest.replayUsed")}: ${replayUsed} · ${t("status.forwardingTest.bodyUnchanged")}: ${bodyUnchanged}</small><small>${t("status.forwardingTest.requestDeviceOriginal")}: ${originalRequestDevice} · ${t("status.forwardingTest.displayName")}: ${displayDeviceName} · ${t("status.forwardingTest.sentDevice")}: ${sentDeviceValue}</small><small>${t("status.forwardingTest.errorLabel")}: ${err}</small>${replayReason}${excerpt}</div>`;
        })
        .join("")
    : `<div class="forwarding-test-row"><small>${t("status.forwardingTest.noAttempts")}</small></div>`;
  const skippedRows = (result.devices_without_position || []).length
    ? result.devices_without_position
        .map((row) => `<span>${escapeHtml(row.device_name || row.device_id || t("common.unknown"))}</span>`)
        .join(", ")
    : t("common.none");
  const replayMissingRows = (result.device_runs || [])
    .filter((row) => !row.replay_available)
    .map((row) => `${row.device_name || row.device_id || t("common.unknown")}${row.replay_reason ? ` (${row.replay_reason})` : ""}`);
  host.innerHTML = `
    <div class="forwarding-test-head">
      <strong>${t("status.forwardingTest.lastRun")}: ${escapeHtml(result.forwarding_name || t("settings.forwardings.fallbackName"))}</strong>
      <small>${t("status.forwardingTest.targetUrl")}: ${escapeHtml(result.target_url || t("common.na"))}</small>
      <small>${t("status.forwardingTest.noteServerSide")}</small>
    </div>
    <div class="forwarding-test-summary">
      <small>${t("status.forwardingTest.devicesTotal")}: ${Number(result.devices_total || 0)}</small>
      <small>${t("status.forwardingTest.withLastPosition")}: ${Number(result.devices_with_position || 0)}</small>
      <small>${t("status.forwardingTest.withoutLastPosition")}: ${escapeHtml(skippedRows)}</small>
      <small>${t("status.forwardingTest.withoutReplayRequest")}: ${escapeHtml(replayMissingRows.length ? replayMissingRows.join(", ") : t("common.none"))}</small>
      <small>${t("status.forwardingTest.attempts")}: ${Number(result.requests_attempted || 0)} · ${t("status.forwardingTest.delivered")}: ${Number(result.requests_delivered || 0)} · ${t("status.forwardingTest.failed")}: ${Number(result.requests_failed || 0)}</small>
    </div>
    <div class="forwarding-test-list">${attemptRows}</div>
  `;
  host.hidden = false;
}

async function openStatusModal() {
  if (ui.statusModalOpen) return;
  const content = document.createElement("div");
  content.className = "status-modal-content";
  content.innerHTML = `
    <section class="settings-section">
      <h3 id="status-system-title">${t("status.system.title")}</h3>
      <div id="status-system-status"></div>
    </section>
    <section class="settings-section">
      <h3 id="status-forwarding-title">${t("status.forwardingErrors.title")}</h3>
      <div id="status-forwarding-errors"></div>
    </section>
    <section class="settings-section">
      <h3 id="status-recent-gps-title">${t("status.recentGps.title")}</h3>
      <div id="status-recent-gps"></div>
    </section>
  `;
  const closeBtn = createButton({ label: t("common.close") });
  const modal = createModal({
    title: `<span class="material-symbols-outlined" aria-hidden="true">monitoring</span><span>${t("status.title")}</span>`,
    content,
    actions: [closeBtn],
    routeHash: "#status",
    clearExistingHashOnOpen: true,
  });
  const baseClose = modal.close.bind(modal);
  modal.close = () => {
    ui.statusModalOpen = false;
    ui.statusModalHost = null;
    baseClose();
  };
  closeBtn.addEventListener("click", () => modal.close());
  modal.open();
  ui.statusModalOpen = true;
  ui.statusModalHost = content;
  try {
    await Promise.all([loadSystemStatus(), loadForwardingErrors(), loadRecentGps()]);
    renderStatusModalContent();
  } catch (err) {
    pushToast(ui.toastArea, err.message, "error");
  }
}

function renderStatusModalContent() {
  if (!ui.statusModalOpen || !ui.statusModalHost) return;
  renderSystemStatus(ui.statusModalHost.querySelector("#status-system-status"));
  renderForwardingErrors(ui.statusModalHost.querySelector("#status-forwarding-errors"));
  renderRecentGps(ui.statusModalHost.querySelector("#status-recent-gps"));
}

function openForwardingModal(existing) {
  const content = document.createElement("div");
  const nameField = createField({ label: t("common.name"), value: existing?.name || "" });
  const ena = createSwitch({
    label: t("common.enabled"),
    value: existing ? !!existing.enabled : true,
    onChange: () => {},
  });
  const urlField = createField({ label: t("settings.forwardings.url"), value: existing?.url || "" });

  const headerSection = document.createElement("div");
  headerSection.className = "forwarding-modal-section";
  const headerTitle = document.createElement("div");
  headerTitle.className = "forwarding-section-title";
  headerTitle.textContent = t("settings.forwardings.header.title");
  const incomingHeadersOnly =
    existing == null || existing.incoming_headers_only !== false;
  const hdrFromDeviceSw = createSwitch({
    label: t("settings.forwardings.header.useIncoming"),
    value: incomingHeadersOnly,
    onChange: (next) => {
      syncHeaderManual(!next);
    },
  });
  const headerBuilderWrap = document.createElement("div");
  headerBuilderWrap.className = "forwarding-header-builder";
  const headerRowsHost = document.createElement("div");
  headerRowsHost.className = "forwarding-header-builder-rows";
  const headerActions = document.createElement("div");
  headerActions.className = "forwarding-header-builder-actions";
  const addHeaderBtn = createButton({ label: t("settings.forwardings.header.add"), icon: "add" });
  addHeaderBtn.classList.add("btn-secondary");
  const headerPreviewTitle = document.createElement("div");
  headerPreviewTitle.className = "forwarding-header-preview-title";
  headerPreviewTitle.textContent = t("settings.forwardings.header.previewTitle");
  const headerPreview = document.createElement("pre");
  headerPreview.className = "forwarding-header-preview";
  const headerError = document.createElement("small");
  headerError.className = "forwarding-header-builder-error";
  const headerRows = Object.entries(existing?.headers || {}).map(([name, value]) => ({
    name: String(name || ""),
    value: String(value || ""),
  }));
  function setHeaderBuilderError(text) {
    headerError.textContent = text || "";
    headerBuilderWrap.classList.toggle("is-error", !!text);
  }
  function renderHeaderPreview() {
    const items = headerRows
      .map((row) => ({
        name: String(row.name || "").trim(),
        value: String(row.value || "").trim(),
      }))
      .filter((row) => row.name && row.value);
    if (!items.length) {
      headerPreview.textContent = t("settings.forwardings.header.none");
      return;
    }
    headerPreview.textContent = items.map((row) => `${row.name}: ${row.value}`).join("\n");
  }
  function renderHeaderRows() {
    headerRowsHost.innerHTML = "";
    headerRows.forEach((row, index) => {
      const rowEl = document.createElement("div");
      rowEl.className = "forwarding-header-row";
      const nameInput = document.createElement("input");
      nameInput.className = "input forwarding-header-name";
      nameInput.placeholder = t("settings.forwardings.header.namePlaceholder");
      nameInput.value = row.name || "";
      const valueInput = document.createElement("input");
      valueInput.className = "input forwarding-header-value";
      valueInput.placeholder = t("settings.forwardings.header.valuePlaceholder");
      valueInput.value = row.value || "";
      const upBtn = createIconButton({
        icon: "arrow_upward",
        title: "Nach oben",
        onClick: () => {
          if (index === 0) return;
          const prev = headerRows[index - 1];
          headerRows[index - 1] = headerRows[index];
          headerRows[index] = prev;
          renderHeaderRows();
        },
      });
      const downBtn = createIconButton({
        icon: "arrow_downward",
        title: "Nach unten",
        onClick: () => {
          if (index >= headerRows.length - 1) return;
          const next = headerRows[index + 1];
          headerRows[index + 1] = headerRows[index];
          headerRows[index] = next;
          renderHeaderRows();
        },
      });
      const removeBtn = createIconButton({
        icon: "delete",
        title: t("settings.forwardings.header.remove"),
        onClick: () => {
          headerRows.splice(index, 1);
          renderHeaderRows();
        },
      });
      removeBtn.classList.add("btn-danger");
      nameInput.addEventListener("input", () => {
        headerRows[index].name = nameInput.value;
        renderHeaderPreview();
      });
      valueInput.addEventListener("input", () => {
        headerRows[index].value = valueInput.value;
        renderHeaderPreview();
      });
      rowEl.append(nameInput, valueInput, upBtn, downBtn, removeBtn);
      headerRowsHost.appendChild(rowEl);
    });
    renderHeaderPreview();
  }
  function sanitizeHeaderRows() {
    const out = {};
    headerRows.forEach((row) => {
      const key = String(row.name || "").trim();
      const value = String(row.value || "").trim();
      if (!key || !value) return;
      out[key] = value;
    });
    return out;
  }
  addHeaderBtn.addEventListener("click", () => {
    headerRows.push({ name: "", value: "" });
    renderHeaderRows();
  });
  headerActions.append(addHeaderBtn);
  headerBuilderWrap.append(headerRowsHost, headerActions, headerPreviewTitle, headerPreview, headerError);
  renderHeaderRows();
  function syncHeaderManual(allowEdit) {
    headerBuilderWrap.hidden = !allowEdit;
  }
  syncHeaderManual(!incomingHeadersOnly);
  headerSection.append(headerTitle, hdrFromDeviceSw.wrap, headerBuilderWrap);

  const bodySection = document.createElement("div");
  bodySection.className = "forwarding-modal-section";
  const bodyTitle = document.createElement("div");
  bodyTitle.className = "forwarding-section-title";
  bodyTitle.textContent = t("settings.forwardings.body.title");
  const bodyFromSrc =
    existing == null || existing.forward_body_from_source !== false;
  const bodyHint = document.createElement("p");
  bodyHint.className = "forwarding-hint";
  const bodyBuilderWrap = document.createElement("div");
  bodyBuilderWrap.className = "forwarding-body-builder";
  const bodyBuilderRows = document.createElement("div");
  bodyBuilderRows.className = "forwarding-body-builder-rows";
  const bodyBuilderActions = document.createElement("div");
  bodyBuilderActions.className = "forwarding-body-builder-actions";
  const addBodyRowBtn = createButton({ label: t("settings.forwardings.body.addField"), icon: "add" });
  addBodyRowBtn.classList.add("btn-secondary");
  const chipsWrap = document.createElement("div");
  chipsWrap.className = "forwarding-body-builder-chips";
  const previewTitle = document.createElement("div");
  previewTitle.className = "forwarding-body-preview-title";
  previewTitle.textContent = t("settings.forwardings.body.previewTitle");
  const preview = document.createElement("pre");
  preview.className = "forwarding-body-preview";
  const builderError = document.createElement("small");
  builderError.className = "forwarding-body-builder-error";
  const bodyRows = Array.isArray(existing?.body_fields) ? existing.body_fields.map((x) => ({ ...x })) : [];
  function defaultBodyRows() {
    return [
      { param: "latitude", source: "latitude" },
      { param: "longitude", source: "longitude" },
      { param: "device", source: "device_name" },
    ];
  }
  if (!bodyRows.length && existing == null) {
    bodyRows.push(...defaultBodyRows());
  }
  function renderBodyBuilderRows() {
    bodyBuilderRows.innerHTML = "";
    bodyRows.forEach((row, index) => {
      const rowEl = document.createElement("div");
      rowEl.className = "forwarding-body-row";
      const paramInput = document.createElement("input");
      paramInput.className = "input forwarding-body-param";
      paramInput.placeholder = t("settings.forwardings.body.paramPlaceholder");
      paramInput.value = row.param || "";
      const sourceSelect = document.createElement("select");
      sourceSelect.className = "select forwarding-body-source";
      sourceSelect.innerHTML = FORWARDING_BODY_VARIABLES.map((entry) => `<option value="${entry.key}">${t(entry.labelKey)}</option>`).join("");
      sourceSelect.value = row.source || FORWARDING_BODY_VARIABLES[0].key;
      const upBtn = createIconButton({
        icon: "arrow_upward",
        title: "Nach oben",
        onClick: () => {
          if (index === 0) return;
          const prev = bodyRows[index - 1];
          bodyRows[index - 1] = bodyRows[index];
          bodyRows[index] = prev;
          renderBodyBuilderRows();
        },
      });
      const downBtn = createIconButton({
        icon: "arrow_downward",
        title: "Nach unten",
        onClick: () => {
          if (index >= bodyRows.length - 1) return;
          const next = bodyRows[index + 1];
          bodyRows[index + 1] = bodyRows[index];
          bodyRows[index] = next;
          renderBodyBuilderRows();
        },
      });
      const removeBtn = createIconButton({
        icon: "delete",
        title: t("settings.forwardings.body.removeField"),
        onClick: () => {
          bodyRows.splice(index, 1);
          renderBodyBuilderRows();
        },
      });
      removeBtn.classList.add("btn-danger");
      paramInput.addEventListener("input", () => {
        bodyRows[index].param = paramInput.value;
        renderBodyBuilderPreview();
      });
      sourceSelect.addEventListener("change", () => {
        bodyRows[index].source = sourceSelect.value;
        renderBodyBuilderPreview();
      });
      rowEl.append(paramInput, sourceSelect, upBtn, downBtn, removeBtn);
      bodyBuilderRows.appendChild(rowEl);
    });
    renderBodyBuilderPreview();
  }
  function renderBodyBuilderPreview() {
    const pairs = bodyRows
      .map((row) => ({
        param: String(row.param || "").trim(),
        source: String(row.source || "").trim(),
      }))
      .filter((row) => row.param && row.source);
    if (!pairs.length) {
      preview.textContent = t("settings.forwardings.body.none");
      return;
    }
    preview.textContent = pairs
      .map((row) => {
        const varLabel = t(FORWARDING_BODY_VARIABLES.find((entry) => entry.key === row.source)?.labelKey || "", {}, row.source);
        return `${encodeURIComponent(row.param)}=<${varLabel}>`;
      })
      .join("&");
  }
  function sanitizeBodyRows() {
    return bodyRows
      .map((row) => ({
        param: String(row.param || "").trim(),
        source: String(row.source || "").trim(),
      }))
      .filter((row) => row.param && row.source);
  }
  function setBodyBuilderError(text) {
    builderError.textContent = text || "";
    bodyBuilderWrap.classList.toggle("is-error", !!text);
  }
  addBodyRowBtn.addEventListener("click", () => {
    bodyRows.push({ param: "", source: FORWARDING_BODY_VARIABLES[0].key });
    renderBodyBuilderRows();
  });
  FORWARDING_BODY_VARIABLES.forEach((entry) => {
    const chip = createButton({
      label: t(entry.labelKey),
      onClick: () => {
        bodyRows.push({ param: entry.key, source: entry.key });
        renderBodyBuilderRows();
      },
    });
    chip.classList.add("btn-secondary", "forwarding-body-chip");
    chipsWrap.appendChild(chip);
  });
  bodyBuilderActions.append(addBodyRowBtn);
  bodyBuilderWrap.append(bodyBuilderRows, bodyBuilderActions, chipsWrap, previewTitle, preview, builderError);
  renderBodyBuilderRows();
  function syncBodyHint(forwardRawBody) {
    if (forwardRawBody) {
      bodyHint.textContent =
        t("settings.forwardings.body.hintRaw");
      bodyBuilderWrap.hidden = true;
    } else {
      bodyHint.textContent =
        t("settings.forwardings.body.hintBuilder");
      bodyBuilderWrap.hidden = false;
    }
  }
  const bodyFromDeviceSw = createSwitch({
    label: t("settings.forwardings.body.useIncoming"),
    value: bodyFromSrc,
    onChange: (next) => {
      syncBodyHint(next);
    },
  });
  syncBodyHint(bodyFromSrc);
  bodySection.append(bodyTitle, bodyFromDeviceSw.wrap, bodyHint, bodyBuilderWrap);

  const sectionsWrap = document.createElement("div");
  sectionsWrap.className = "forwarding-modal-sections";
  sectionsWrap.append(headerSection, bodySection);
  content.append(nameField.field, ena.wrap, urlField.field, sectionsWrap);
  const cancelBtn = createButton({ label: t("common.cancel") });
  const primaryLabel = existing ? t("common.save") : t("common.add");
  const primaryBtn = createButton({ label: primaryLabel, icon: existing ? "check" : "add" });
  primaryBtn.classList.add("btn-primary");
  const modal = createModal({
    title: existing ? t("settings.forwardings.edit") : t("settings.forwardings.add"),
    content,
    actions: [cancelBtn, primaryBtn],
  });
  cancelBtn.addEventListener("click", () => modal.close());
  primaryBtn.addEventListener("click", async () => {
    const incoming_headers_only = hdrFromDeviceSw.toggle.classList.contains("enabled");
    const forward_body_from_source = bodyFromDeviceSw.toggle.classList.contains("enabled");
    const headersObj = incoming_headers_only ? {} : sanitizeHeaderRows();
    setHeaderBuilderError("");
    if (!incoming_headers_only && Object.keys(headersObj).length === 0) {
      setHeaderBuilderError(t("settings.forwardings.header.required"));
      return;
    }
    const body_fields = sanitizeBodyRows();
    setBodyBuilderError("");
    if (!forward_body_from_source && body_fields.length === 0) {
      setBodyBuilderError(t("settings.forwardings.body.required"));
      return;
    }
    const enabled = ena.toggle.classList.contains("enabled");
    const name = nameField.input.value.trim();
    const url = urlField.input.value.trim();
    if (!name) {
      setFieldState(nameField, "error", t("errors.nameRequired"));
      return;
    }
    setFieldState(nameField, "default", "");
    if (!url) {
      setFieldState(urlField, "error", t("errors.urlRequired"));
      return;
    }
    if (!isHttpUrl(url)) {
      setFieldState(urlField, "error", t("errors.urlProtocol"));
      return;
    }
    setFieldState(urlField, "default", "");
    setButtonLoading(primaryBtn, true, t("common.saving"));
    try {
      if (existing) {
        await api(`/api/forwardings/${existing.id}`, {
          method: "PUT",
          body: JSON.stringify({
            name,
            url,
            headers: headersObj,
            enabled,
            incoming_headers_only,
            forward_body_from_source,
            body_fields,
          }),
        });
      } else {
        await api("/api/forwardings", {
          method: "POST",
          body: JSON.stringify({
            name,
            url,
            headers: headersObj,
            enabled,
            incoming_headers_only,
            forward_body_from_source,
            body_fields,
          }),
        });
      }
      await loadSettings();
      renderForwardingList();
      pushToast(ui.toastArea, existing ? t("settings.forwardings.saved") : t("settings.forwardings.added"), "success");
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
    empty.textContent = t("settings.forwardings.empty");
    host.appendChild(empty);
    return;
  }
  list.forEach((f) => {
    const item = document.createElement("div");
    item.className = "list-item list-item-managed";
    item.dataset.forwardingName = f.name || "";
    item.dataset.incomingHeadersOnly = String(f.incoming_headers_only !== false);
    item.dataset.forwardBodyFromSource = String(f.forward_body_from_source !== false);
    const leading = document.createElement("div");
    leading.className = "list-item-leading list-item-leading-icon";
    leading.innerHTML = '<span class="material-symbols-outlined" aria-hidden="true">alt_route</span>';
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
    const body = document.createElement("div");
    body.className = "list-item-body";
    const titleEl = document.createElement("strong");
    titleEl.textContent = f.name || t("settings.forwardings.fallbackName");
    const u = document.createElement("small");
    u.textContent = f.url || "";
    const meta = document.createElement("small");
    meta.className = "list-item-meta";
    const bits = [];
    if (f.incoming_headers_only === false) bits.push(t("settings.forwardings.summary.headerManual"));
    if (f.forward_body_from_source === false) bits.push(t("settings.forwardings.summary.bodyEmpty"));
    meta.textContent = bits.length ? bits.join(" · ") : "";
    body.append(titleEl, document.createElement("br"), u);
    if (meta.textContent) body.append(document.createElement("br"), meta);
    const actions = document.createElement("div");
    actions.className = "ui-item-actions";
    const testBtn = createIconButton({
      icon: "science",
      title: t("settings.forwardings.test"),
      onClick: () => runForwardingTest(f, testBtn),
    });
    testBtn.dataset.forwardingAction = "test";
    testBtn.setAttribute("aria-label", t("settings.forwardings.testAria", { name: f.name || "" }));
    const editBtn = createIconButton({
      icon: "edit",
      title: t("common.edit"),
      onClick: () => openForwardingModal(f),
    });
    editBtn.dataset.forwardingAction = "edit";
    editBtn.setAttribute("aria-label", t("settings.forwardings.editAria", { name: f.name || "" }));
    const delBtn = createIconButton({
      icon: "delete",
      title: t("common.delete"),
      onClick: () => openDeleteForwardingModal(f),
    });
    delBtn.dataset.forwardingAction = "delete";
    delBtn.setAttribute("aria-label", t("settings.forwardings.deleteAria", { name: f.name || "" }));
    delBtn.classList.add("btn-danger");
    sw.wrap.classList.add("settings-inline-switch");
    actions.append(sw.wrap, testBtn, editBtn, delBtn);
    item.append(leading, body, actions);
    host.appendChild(item);
  });
  renderForwardingTestResult();
}

async function runForwardingTest(forwarding, triggerBtn = null) {
  if (triggerBtn) {
    triggerBtn.disabled = true;
    triggerBtn.classList.add("loading");
  }
  try {
    const res = await api(`/api/forwardings/${forwarding.id}/test`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    const result = res.result || {};
    const allRuns = Array.isArray(result.device_runs) ? result.device_runs : [];
    allRuns.forEach((run) => {
      const attempts = Array.isArray(run.attempts) ? run.attempts : [];
      attempts.forEach((attempt, index) => {
        const forwardingName = attempt.forwarding_name || result.forwarding_name || forwarding.name || t("settings.forwardings.fallbackName");
        const deviceName = run.device_name || run.device_id || t("common.unknown");
        console.group(`[GPSLOGGER TEST] ${deviceName} -> ${forwardingName} #${index + 1}`);
        console.log("--- GPSLOGGER TEST REQUEST ---");
        console.log(`Method: ${attempt.final_request_method || attempt.request_method || "POST"}`);
        console.log(`URL: ${attempt.final_request_url || attempt.target_url || "—"}`);
        console.log("Headers:");
        const hdr = attempt.final_request_headers && typeof attempt.final_request_headers === "object" ? attempt.final_request_headers : {};
        Object.entries(hdr).forEach(([k, v]) => {
          console.log(`  ${k}: ${v}`);
        });
        if (!Object.keys(hdr).length) {
          console.log("  (keine Headerdaten)");
        }
        console.log("Body:");
        console.log(attempt.final_request_body_text ?? "");
        console.log("--- RESPONSE ---");
        console.log(`Status: ${attempt.response_status ?? attempt.http_status ?? "—"}`);
        const responseText = String(attempt.response_body_text || "");
        console.log("Body:");
        console.log(responseText.length > 1000 ? `${responseText.slice(0, 1000)} ...[gekürzt]` : responseText || "—");
        console.log("--- META ---");
        console.log(`Body source: ${attempt.body_source || attempt.replay_reason || "unbekannt"}`);
        console.log(`Header source: ${attempt.header_source || "unbekannt"}`);
        console.log(`Body unchanged: ${Boolean(attempt.body_unchanged)}`);
        console.log(`Original request device: ${attempt.original_request_device || "—"}`);
        console.log(`Device display name: ${attempt.device_display_name || "—"}`);
        console.log(`Sent device value: ${attempt.sent_device_value || "—"}`);
        console.log(`Device: ${deviceName}`);
        console.log(`Forwarding: ${forwardingName}`);
        console.groupEnd();
      });
    });
    state.lastForwardingTestResult = result;
    renderForwardingTestResult();
    const devicesTotal = Number(result.devices_total || 0);
    const withPosition = Number(result.devices_with_position || 0);
    const delivered = Number(result.requests_delivered || 0);
    const failed = Number(result.requests_failed || 0);
    const firstFailure = (result.device_runs || [])
      .flatMap((run) => run.attempts || [])
      .find((attempt) => !attempt.ok);
    if (devicesTotal === 0) {
      pushToast(ui.toastArea, {
        level: "info",
        title: t("status.forwardingTest.noneExecuted"),
        description: t("status.forwardingTest.noDevices"),
      });
      return;
    }
    if (withPosition === 0) {
      pushToast(ui.toastArea, {
        level: "info",
        title: t("status.forwardingTest.noneExecuted"),
        description: t("status.forwardingTest.noLastPosition"),
      });
      return;
    }
    if (delivered > 0 && failed === 0) {
      pushToast(ui.toastArea, {
        level: "success",
        title: t("status.forwardingTest.tested"),
        description: t("status.forwardingTest.successDelivered", { count: delivered }),
      });
      return;
    }
    if (delivered > 0 && failed > 0) {
      pushToast(ui.toastArea, {
        level: "info",
        title: t("status.forwardingTest.partialFailed"),
        description: t("status.forwardingTest.partialDelivered", { delivered, total: delivered + failed }),
      });
      return;
    }
    const failureMsg = firstFailure?.http_status
      ? t("status.forwardingTest.failedHttp", { status: firstFailure.http_status })
      : firstFailure?.error
        ? t("status.forwardingTest.failedError", { error: firstFailure.error })
        : t("status.forwardingTest.failedUnreachable");
    pushToast(ui.toastArea, {
      level: "error",
      title: t("status.forwardingTest.failed"),
      description: failureMsg,
    });
  } catch (err) {
    state.lastForwardingTestResult = null;
    renderForwardingTestResult();
    pushToast(ui.toastArea, {
      level: "error",
      title: t("status.forwardingTest.failed"),
      description: err.message,
    });
  } finally {
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.classList.remove("loading");
    }
  }
}

function openDeleteForwardingModal(f) {
  openConfirmModal({
    title: t("settings.forwardings.deleteTitle"),
    message: t("settings.forwardings.deleteConfirm", { name: f.name }),
    confirmLabel: t("common.delete"),
    onConfirm: async () => {
      try {
        await api(`/api/forwardings/${f.id}`, { method: "DELETE" });
        await loadSettings();
        renderForwardingList();
        pushToast(ui.toastArea, t("settings.forwardings.deleted"), "success");
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
        throw err;
      }
    },
  });
}

function renderSystemStatus(host = null) {
  const target = host || document.getElementById("settings-system-status");
  if (!target) return;
  const status = state.systemStatus || {};
  const uptime = Number(status.uptime_seconds || 0);
  const h = Math.floor(uptime / 3600);
  const m = Math.floor((uptime % 3600) / 60);
  const s = uptime % 60;
  const locale = currentLanguage === "de" ? "de-DE" : "en-US";
  const lastNasRun = status.last_nas_run_at ? new Date(status.last_nas_run_at).toLocaleString(locale) : t("status.system.noRunYet");
  const lastNasError = status.last_nas_error || t("status.system.noError");
  target.innerHTML = `
    <div class="list">
      <div class="list-item"><span>${t("status.system.uptime")}</span><strong>${h}h ${m}m ${s}s</strong></div>
      <div class="list-item"><span>${t("status.system.devices")}</span><strong>${status.device_count ?? 0}</strong></div>
      <div class="list-item"><span>${t("status.system.forwardingQueue")}</span><strong>${status.forward_queue_size ?? 0}</strong></div>
      <div class="list-item"><span>${t("status.system.pendingNas")}</span><strong>${status.pending_nas_count ?? 0}</strong></div>
      <div class="list-item"><span>${t("status.system.storedStatuses")}</span><strong>${status.stored_status_count ?? 0}</strong></div>
      <div class="list-item"><span>${t("status.system.lastNasRun")}</span><strong>${lastNasRun}</strong></div>
      <div class="list-item"><span>${t("status.system.lastNasSaved")}</span><strong>${status.last_nas_saved_count ?? 0}</strong></div>
      <div class="list-item"><span>${t("status.system.nasErrorState")}</span><small>${lastNasError}</small></div>
    </div>
  `;
}

function renderForwardingErrors(host = null) {
  const target = host || document.getElementById("settings-forwarding-errors");
  if (!target) return;
  const errors = state.forwardingErrors || [];
  const rows = errors.length
    ? errors
        .map(
          (entry) =>
            `<div class="list-item"><span>${new Date(entry.time).toLocaleString(currentLanguage === "de" ? "de-DE" : "en-US")}</span><small>${entry.message}</small></div>`,
        )
        .join("")
    : `<div class="list-item"><span>${t("status.forwardingErrors.none")}</span></div>`;
  target.innerHTML = `
    <div class="panel-head">
      <div class="panel-actions">
        <button data-action="reload-forwarding-errors" class="btn">${t("common.reload")}</button>
        <button data-action="clear-forwarding-errors" class="btn">${t("common.clear")}</button>
      </div>
    </div>
    <div class="list">${rows}</div>
  `;
  const btn = target.querySelector('[data-action="reload-forwarding-errors"]');
  btn?.addEventListener("click", async () => {
    setButtonLoading(btn, true, t("common.loading"));
    try {
      await loadForwardingErrors();
      renderForwardingErrors(target);
    } finally {
      setButtonLoading(btn, false);
    }
  });
  const clearBtn = target.querySelector('[data-action="clear-forwarding-errors"]');
  clearBtn?.addEventListener("click", async () => {
    setButtonLoading(clearBtn, true, t("common.clearing"));
    try {
      await api("/api/forwarding/errors/clear", { method: "POST" });
      await loadForwardingErrors();
      renderForwardingErrors(target);
    } finally {
      setButtonLoading(clearBtn, false);
    }
  });
}

function renderRecentGps(host = null) {
  const target = host || document.getElementById("settings-recent-gps");
  if (!target) return;
  const rows = (state.recentGps || [])
    .map((entry) => {
      const title = entry.device_name || entry.device_id || t("common.unknown");
      const ts = entry.timestamp ? new Date(entry.timestamp).toLocaleString(currentLanguage === "de" ? "de-DE" : "en-US") : t("common.na");
      const parts = [
        `${entry.latitude}, ${entry.longitude}`,
        entry.accuracy != null ? `${t("status.recentGps.acc")} ${entry.accuracy}` : null,
        entry.device != null && entry.device !== "" ? `${t("status.recentGps.client")}: ${entry.device}` : null,
        entry.battery != null && entry.battery !== "" ? `${t("status.recentGps.battery")} ${entry.battery}` : null,
        entry.speed != null ? `v ${entry.speed}` : null,
        entry.direction != null ? `↗ ${entry.direction}` : null,
        entry.altitude != null ? `alt ${entry.altitude}` : null,
        entry.provider ? String(entry.provider) : null,
        entry.activity ? String(entry.activity) : null,
        entry.ingest_route ? entry.ingest_route : null,
      ].filter(Boolean);
      return `<div class="list-item"><span>${escapeHtml(title)} | ${escapeHtml(ts)}</span><small>${escapeHtml(parts.join(" · "))}</small></div>`;
    })
    .join("");
  target.innerHTML = `
    <div class="panel-head">
      <div class="panel-actions">
        <button data-action="reload-recent-gps" class="btn">${t("common.reload")}</button>
      </div>
    </div>
    <div class="list">${rows || `<div class="list-item"><span>${t("status.recentGps.none")}</span></div>`}</div>
  `;
  const btn = target.querySelector('[data-action="reload-recent-gps"]');
  btn?.addEventListener("click", async () => {
    setButtonLoading(btn, true, t("common.loading"));
    try {
      await loadRecentGps();
      renderRecentGps(target);
    } finally {
      setButtonLoading(btn, false);
    }
  });
}

function syncMetaThemeColor() {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) {
    return;
  }
  const v = getComputedStyle(document.documentElement).getPropertyValue("--color-primary").trim();
  if (v) {
    meta.setAttribute("content", v);
  }
}

function applyTheme(name) {
  let link = document.getElementById("theme-link");
  if (!link) {
    link = document.createElement("link");
    link.id = "theme-link";
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  link.onload = () => {
    syncMetaThemeColor();
  };
  link.href = `/themes/${name}/theme.css`;
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    return;
  }
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((err) => {
    console.warn("[gpslogger] Service Worker Registrierung fehlgeschlagen", err);
  });
}

async function loadDevices() {
  const data = await api("/api/devices");
  state.devices = data.devices || [];
  migrateMapDeviceSelection();
  syncVisibleDevicesWithLoadedDevices();
  renderMapDeviceList();
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
