import {
  createButton,
  createField,
  createIconButton,
  createModal,
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

/** Relative Zeit bis zum angegebenen Zeitpunkt (nur Vergangenheit), z. B. „vor 2 Min.“ */
function formatRelativeTimeDe(isoString) {
  const t = new Date(isoString).getTime();
  if (Number.isNaN(t)) return "—";
  const diffMs = Math.max(0, Date.now() - t);
  const sec = Math.floor(diffMs / 1000);
  if (sec < 45) return "gerade eben";
  const min = Math.floor(diffMs / 60000);
  if (min < 60) return min === 1 ? "vor 1 Min." : `vor ${min} Min.`;
  const h = Math.floor(min / 60);
  if (h < 24) return h === 1 ? "vor 1 Stunde" : `vor ${h} Stunden`;
  const d = Math.floor(h / 24);
  if (d < 7) return d === 1 ? "vor 1 Tag" : `vor ${d} Tagen`;
  const w = Math.floor(d / 7);
  if (w < 5) return w === 1 ? "vor 1 Woche" : `vor ${w} Wochen`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return mo === 1 ? "vor 1 Monat" : `vor ${mo} Monaten`;
  const y = Math.floor(d / 365);
  return y === 1 ? "vor 1 Jahr" : `vor ${y} Jahren`;
}

const ui = {
  pages: {},
  toastArea: null,
  map: null,
  mapFitControl: null,
  layers: {},
  markers: new Map(),
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
  { key: "latitude", label: "Latitude" },
  { key: "longitude", label: "Longitude" },
  { key: "device_name", label: "Gerätename" },
  { key: "accuracy", label: "Accuracy" },
  { key: "battery", label: "Battery" },
  { key: "speed", label: "Speed" },
  { key: "direction", label: "Direction" },
  { key: "altitude", label: "Altitude" },
  { key: "provider", label: "Provider" },
  { key: "activity", label: "Activity" },
  { key: "timestamp", label: "Timestamp/Zeit" },
  { key: "device_id", label: "Device ID" },
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
  if (!res.ok) throw new Error(data.error || "API Fehler");
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
  text.textContent = "GPSLogger wird neu gestartet...";
  content.append(spin, text);

  const modal = createModal({
    title: "Neustart",
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
  ui.toastArea = createToastArea();
  document.body.appendChild(ui.toastArea);
  initInkRipple();

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
    marker.bindTooltip(escapeHtml(formatRelativeTimeDe(livePoint.timestamp)), {
      permanent: true,
      direction: "top",
      offset: [0, -10],
      className: "map-live-age-tooltip",
    });
    marker.bindPopup(buildPositionTooltipHtml(livePoint, device.name), {
      className: "map-point-tooltip",
    });
    ui.markers.set(device.id, marker);
    allLatLng.push([livePoint.latitude, livePoint.longitude]);
  });
  if (!preserveView && allLatLng.length) {
    const bounds = L.latLngBounds(allLatLng);
    if (bounds.isValid()) ui.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 18 });
  }
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
    empty.textContent = "Keine Geräte angelegt.";
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
    paletteBtn.setAttribute("aria-label", "Farbe wählen");
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
  layout.classList.toggle("map-layout--drawer-open", !!open);
  toggle.classList.toggle("is-active", !!open);
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.setAttribute("aria-label", open ? "Menü schließen" : "Menü öffnen");
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
    pushToast(ui.toastArea, "Keine sichtbaren Punkte zum Einpassen.", "error");
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
      btn.setAttribute("aria-label", "Auf sichtbare Punkte einpassen");
      btn.title = "Auf sichtbare Punkte einpassen";
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
    throw new Error("Einstellungen sind nicht geladen.");
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
  pushToast(ui.toastArea, "Einstellungen gespeichert", "success");
  ui.settingsDirty = false;
}

function openUnsavedSettingsCloseConfirm(afterResolved) {
  if (ui.settingsUnsavedDialogOpen) return;
  ui.settingsUnsavedDialogOpen = true;
  const message = document.createElement("div");
  message.textContent =
    "Es gibt nicht gespeicherte Änderungen an NAS-Pfad, Intervall oder Theme. Speichern oder verwerfen?";
  const discardBtn = createButton({ label: "Einstellungen verwerfen" });
  discardBtn.classList.add("btn-secondary");
  const saveBtn = createButton({ label: "Speichern", icon: "check" });
  saveBtn.classList.add("btn-primary");
  const modal = createModal({
    title: "Ungespeicherte Änderungen",
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
    setButtonLoading(saveBtn, true, "Speichert...");
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
  deviceListLabel.className = "field-label-text";
  deviceListLabel.textContent = "Geräte";
  const deviceList = document.createElement("div");
  deviceList.id = "map-device-list";
  deviceList.className = "map-device-list";
  deviceList.setAttribute("role", "group");
  deviceList.setAttribute("aria-label", "Geräte ein- und ausblenden");
  deviceListHost.append(deviceListLabel, deviceList);
  const rangeField = document.createElement("div");
  rangeField.className = "field";
  const rangeLabel = document.createElement("span");
  rangeLabel.className = "field-label-text";
  rangeLabel.textContent = "Zeitraum";
  const rangePicker = document.createElement("div");
  rangePicker.className = "segmented map-range-picker";
  const ranges = [
    { value: MAP_RANGE_CURRENT, label: "Aktuelle Position" },
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
      refreshMapData({ fromField, toField });
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
  const footer = document.createElement("div");
  footer.className = "map-filters-footer";
  const statusBtn = createButton({
    label: "Status",
    icon: "monitoring",
    onClick: () => openStatusModal(),
  });
  statusBtn.classList.add("btn-secondary", "map-settings-btn");
  const settingsBtn = createButton({
    label: "Einstellungen",
    icon: "settings",
    onClick: () => openSettingsModal(),
  });
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
    label: "Satellit",
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
  if (ui.mapRange === MAP_RANGE_CURRENT) {
    if (opts.reloadBtn) {
      setButtonLoading(opts.reloadBtn, true, "Lädt...");
    }
    try {
      await drawCurrentPositionsOnly({ preserveView: !!opts.preserveView });
    } catch (err) {
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
    return;
  }

  if (opts.reloadBtn) {
    setButtonLoading(opts.reloadBtn, true, "Lädt...");
  }
  const query = new URLSearchParams();
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  try {
    const data = await api(`/api/positions?${query.toString()}`);
    const positions = data.positions || [];
    setFieldState(fromField, "success", "");
    setFieldState(toField, "success", "");
    drawPositions(positions, { preserveView: !!opts.preserveView });
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
  if (!filtered.length) return;

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
    marker.bindTooltip(escapeHtml(formatRelativeTimeDe(latest.timestamp)), {
      permanent: true,
      direction: "top",
      offset: [0, -10],
      className: "map-live-age-tooltip",
    });
    marker.bindPopup(buildPositionTooltipHtml(latest), {
      className: "map-point-tooltip map-point-tooltip--live",
    });
    marker.addTo(ui.map);
    ui.markers.set(latest.device_id, marker);
  });

  if (!preserveView) {
    const bounds = L.latLngBounds(allLatLng);
    if (bounds.isValid()) ui.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 18 });
  }
}

function renderDevicesSection() {
  const createHost = document.getElementById("devices-add-host");
  const listHost = document.getElementById("devices-list");
  if (!createHost || !listHost) return;
  createHost.innerHTML = "";
  const addBtn = createIconButton({
    icon: "add",
    title: "Gerät hinzufügen",
    onClick: () => openDeviceEditorModal(),
  });
  addBtn.setAttribute("aria-label", "Gerät hinzufügen");
  addBtn.classList.add("btn-primary");
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
    const seen = status?.last_seen ? new Date(status.last_seen).toLocaleString("de-DE") : "Nie";
    const position =
      status?.latitude != null && status?.longitude != null
        ? `${Number(status.latitude).toFixed(5)}, ${Number(status.longitude).toFixed(5)}`
        : "Keine Position";
    const statBits = [];
    if (status?.battery != null && status.battery !== "") statBits.push(`Akku: ${status.battery}`);
    if (status?.speed != null) statBits.push(`Geschw.: ${status.speed}`);
    if (status?.provider) statBits.push(String(status.provider));
    if (status?.activity) statBits.push(String(status.activity));
    const statExtra = statBits.length
      ? `<br><small>${statBits.map((t) => escapeHtml(t)).join(" · ")}</small>`
      : "";
    info.innerHTML = `<strong>${escapeHtml(device.name)}</strong><br><small>Last Seen: ${escapeHtml(seen)}</small><br><small>Pos: ${escapeHtml(position)}</small>${statExtra}`;
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
        <h2><span class="material-symbols-outlined" aria-hidden="true">settings</span><span>Einstellungen</span></h2>
        <button type="button" class="icon-btn settings-modal-close" data-action="close-settings" aria-label="Einstellungen schließen">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>
      <section class="settings-section">
        <h3>Theme</h3>
        <div id="settings-theme" class="ui-form-grid"></div>
      </section>
      <section class="settings-section">
        <h3>Speicherung</h3>
        <div id="settings-storage" class="ui-form-grid"></div>
      </section>
      <section class="settings-section">
        <div class="settings-section-head">
          <h3>Weiterleitungen</h3>
          <div id="forwarding-add-host"></div>
        </div>
        <div id="settings-forwarding" class="settings-forwarding-block">
          <div id="forwardings-list" class="list ui-list"></div>
          <div id="forwarding-test-result" class="forwarding-test-result" hidden></div>
        </div>
      </section>
      <section class="settings-section">
        <div class="settings-section-head">
          <h3>Geräte</h3>
          <div id="devices-add-host"></div>
        </div>
        <div id="devices-list" class="list ui-list"></div>
      </section>
      <section class="settings-section">
        <h3>Aktionen</h3>
        <div id="settings-actions" class="ui-form-grid"></div>
      </section>
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
        await persistMainSettingsFromUi();
      } catch (err) {
        pushToast(ui.toastArea, err.message, "error");
      } finally {
        setButtonLoading(saveBtn, false);
      }
    },
  });
  saveBtn.classList.add("btn-primary", "btn-settings-save");

  themeSelect.input.addEventListener("change", () => {
    applyTheme(themeSelect.input.value);
    ui.settingsDirty = true;
  });
  nasInterval.input.addEventListener("input", () => {
    ui.settingsDirty = true;
  });
  nasPath.input.addEventListener("input", () => {
    ui.settingsDirty = true;
  });
  themeHost.append(themeSelect.field);
  storageHost.append(nasInterval.field, nasPath.field, saveNowBtn);
  const addFwBtn = createIconButton({
    icon: "add",
    title: "Neue Weiterleitung hinzufügen",
    onClick: () => openForwardingModal(null),
  });
  addFwBtn.setAttribute("aria-label", "Neue Weiterleitung hinzufügen");
  addFwBtn.classList.add("btn-primary");
  forwardingAddHost?.appendChild(addFwBtn);
  renderForwardingList();
  const actionsHost = page.querySelector("#settings-actions");
  const restartBtn = createButton({
    label: "GPSLogger neustarten",
    icon: "refresh",
    onClick: () => runGpsloggerRestart(restartBtn),
  });
  restartBtn.id = "settings-restart-btn";
  restartBtn.classList.add("btn-secondary");
  actionsHost?.appendChild(restartBtn);
  const saveFooter = page.querySelector("#settings-save-footer");
  saveFooter?.appendChild(saveBtn);
  ui.settingsFormRefs = { nasInterval, nasPath, themeSelect, saveBtn };
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
        device_name: run.device_name || run.device_id || "Unbekannt",
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
              : "Fehler";
          const stage = entry.stage || "unbekannt";
          const err = entry.error ? escapeHtml(entry.error) : "—";
          const excerpt = entry.response_excerpt ? `<small>Antwort: ${escapeHtml(entry.response_excerpt)}</small>` : "";
          const method = escapeHtml(entry.request_method || "POST");
          const contentType = escapeHtml(entry.request_content_type || "—");
          const replayFlag = entry.replay_available ? "ja" : "nein";
          const replayUsed = entry.replay_used ? "ja" : "nein";
          const bodyUnchanged = entry.body_unchanged ? "ja" : "nein";
          const replayReason = entry.replay_reason ? `<small>Replay-Hinweis: ${escapeHtml(entry.replay_reason)}</small>` : "";
          return `<div class="forwarding-test-row"><strong>${escapeHtml(entry.device_name)}</strong><small>${escapeHtml(statusText)} · Phase: ${escapeHtml(stage)} · Request gesendet: ${entry.request_sent ? "ja" : "nein"} · Quelle: ${escapeHtml(entry.used_source)}</small><small>Ziel: ${escapeHtml(entry.target_url || "—")}</small><small>Methode: ${method} · Content-Type: ${contentType}</small><small>Replay vorhanden: ${replayFlag} · Replay verwendet: ${replayUsed} · Body unverändert: ${bodyUnchanged}</small><small>Fehler: ${err}</small>${replayReason}${excerpt}</div>`;
        })
        .join("")
    : `<div class="forwarding-test-row"><small>Keine Versuche ausgeführt.</small></div>`;
  const skippedRows = (result.devices_without_position || []).length
    ? result.devices_without_position
        .map((row) => `<span>${escapeHtml(row.device_name || row.device_id || "Unbekannt")}</span>`)
        .join(", ")
    : "Keine";
  const replayMissingRows = (result.device_runs || [])
    .filter((row) => !row.replay_available)
    .map((row) => `${row.device_name || row.device_id || "Unbekannt"}${row.replay_reason ? ` (${row.replay_reason})` : ""}`);
  host.innerHTML = `
    <div class="forwarding-test-head">
      <strong>Letzter Testlauf: ${escapeHtml(result.forwarding_name || "Weiterleitung")}</strong>
      <small>Ziel-URL: ${escapeHtml(result.target_url || "—")}</small>
      <small>Hinweis: Zielrequest wird serverseitig ausgeführt und ist im Browser-Netzwerk nicht direkt sichtbar.</small>
    </div>
    <div class="forwarding-test-summary">
      <small>Geräte gesamt: ${Number(result.devices_total || 0)}</small>
      <small>Mit letzter Position: ${Number(result.devices_with_position || 0)}</small>
      <small>Ohne letzte Position: ${escapeHtml(skippedRows)}</small>
      <small>Ohne Replay-Request: ${escapeHtml(replayMissingRows.length ? replayMissingRows.join(", ") : "Keine")}</small>
      <small>Versuche: ${Number(result.requests_attempted || 0)} · Erfolgreich: ${Number(result.requests_delivered || 0)} · Fehlgeschlagen: ${Number(result.requests_failed || 0)}</small>
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
      <h3>Systemstatus</h3>
      <div id="status-system-status"></div>
    </section>
    <section class="settings-section">
      <h3>Forwarding Fehler</h3>
      <div id="status-forwarding-errors"></div>
    </section>
    <section class="settings-section">
      <h3>Letzte GPS Requests</h3>
      <div id="status-recent-gps"></div>
    </section>
  `;
  const closeBtn = createButton({ label: "Schließen" });
  const modal = createModal({
    title: '<span class="material-symbols-outlined" aria-hidden="true">monitoring</span><span>Status</span>',
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
  const nameField = createField({ label: "Name", value: existing?.name || "" });
  const ena = createSwitch({
    label: "Aktiviert",
    value: existing ? !!existing.enabled : true,
    onChange: () => {},
  });
  const urlField = createField({ label: "Forwarding-URL", value: existing?.url || "" });

  const headerSection = document.createElement("div");
  headerSection.className = "forwarding-modal-section";
  const headerTitle = document.createElement("div");
  headerTitle.className = "forwarding-section-title";
  headerTitle.textContent = "Header";
  const incomingHeadersOnly =
    existing == null || existing.incoming_headers_only !== false;
  const hdrFromDeviceSw = createSwitch({
    label: "HTTP-Header der eingehenden Geräte-Anfrage übernehmen",
    value: incomingHeadersOnly,
    onChange: (next) => {
      syncHeaderManual(!next);
    },
  });
  const headersField = createField({
    label: "Manuelle Header (JSON)",
    type: "textarea",
    value: existing ? JSON.stringify(existing.headers || {}, null, 2) : "{}",
    placeholder: "Nur wenn Übernahme oben aus ist",
  });
  function syncHeaderManual(allowEdit) {
    headersField.input.disabled = !allowEdit;
    headersField.field.classList.toggle("is-disabled", !allowEdit);
  }
  syncHeaderManual(!incomingHeadersOnly);
  headerSection.append(headerTitle, hdrFromDeviceSw.wrap, headersField.field);

  const bodySection = document.createElement("div");
  bodySection.className = "forwarding-modal-section";
  const bodyTitle = document.createElement("div");
  bodyTitle.className = "forwarding-section-title";
  bodyTitle.textContent = "HTTP Body";
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
  const addBodyRowBtn = createButton({ label: "Feld hinzufügen", icon: "add" });
  addBodyRowBtn.classList.add("btn-secondary");
  const chipsWrap = document.createElement("div");
  chipsWrap.className = "forwarding-body-builder-chips";
  const previewTitle = document.createElement("div");
  previewTitle.className = "forwarding-body-preview-title";
  previewTitle.textContent = "Vorschau (read only)";
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
      paramInput.placeholder = "Parametername";
      paramInput.value = row.param || "";
      const sourceSelect = document.createElement("select");
      sourceSelect.className = "select forwarding-body-source";
      sourceSelect.innerHTML = FORWARDING_BODY_VARIABLES.map((entry) => `<option value="${entry.key}">${entry.label}</option>`).join("");
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
        title: "Feld entfernen",
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
      preview.textContent = "Kein Body-Feld konfiguriert.";
      return;
    }
    preview.textContent = pairs
      .map((row) => {
        const varLabel = FORWARDING_BODY_VARIABLES.find((entry) => entry.key === row.source)?.label || row.source;
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
      label: entry.label,
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
        "Der Roh-Body der Geräte-Anfrage (z. B. application/x-www-form-urlencoded) wird unverändert als POST an die Ziel-URL gesendet. Eine manuelle Body-Eingabe entfällt.";
      bodyBuilderWrap.hidden = true;
    } else {
      bodyHint.textContent =
        "Der HTTP-Body wird über den Body-Builder aus bekannten Variablen aufgebaut.";
      bodyBuilderWrap.hidden = false;
    }
  }
  const bodyFromDeviceSw = createSwitch({
    label: "HTTP-Body der eingehenden Geräte-Anfrage übernehmen",
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
    const incoming_headers_only = hdrFromDeviceSw.toggle.classList.contains("enabled");
    const forward_body_from_source = bodyFromDeviceSw.toggle.classList.contains("enabled");
    const body_fields = sanitizeBodyRows();
    setBodyBuilderError("");
    if (!forward_body_from_source && body_fields.length === 0) {
      setBodyBuilderError("Bitte mindestens ein Body-Feld konfigurieren.");
      return;
    }
    let headersObj = {};
    if (!incoming_headers_only) {
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
    const t = document.createElement("strong");
    t.textContent = f.name || "Weiterleitung";
    const u = document.createElement("small");
    u.textContent = f.url || "";
    const meta = document.createElement("small");
    meta.className = "list-item-meta";
    const bits = [];
    if (f.incoming_headers_only === false) bits.push("Header: manuell (JSON)");
    if (f.forward_body_from_source === false) bits.push("Body: leer");
    meta.textContent = bits.length ? bits.join(" · ") : "";
    body.append(t, document.createElement("br"), u);
    if (meta.textContent) body.append(document.createElement("br"), meta);
    const actions = document.createElement("div");
    actions.className = "ui-item-actions";
    const testBtn = createIconButton({
      icon: "science",
      title: "Testen",
      onClick: () => runForwardingTest(f, testBtn),
    });
    testBtn.setAttribute("aria-label", `Weiterleitung ${f.name || ""} testen`);
    const editBtn = createIconButton({
      icon: "edit",
      title: "Bearbeiten",
      onClick: () => openForwardingModal(f),
    });
    editBtn.setAttribute("aria-label", `Weiterleitung ${f.name || ""} bearbeiten`);
    const delBtn = createIconButton({
      icon: "delete",
      title: "Löschen",
      onClick: () => openDeleteForwardingModal(f),
    });
    delBtn.setAttribute("aria-label", `Weiterleitung ${f.name || ""} löschen`);
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
        title: "Kein Test durchgeführt",
        description: "Es sind keine Geräte vorhanden.",
      });
      return;
    }
    if (withPosition === 0) {
      pushToast(ui.toastArea, {
        level: "info",
        title: "Kein Test durchgeführt",
        description: "Kein Gerät hat eine letzte Position.",
      });
      return;
    }
    if (delivered > 0 && failed === 0) {
      pushToast(ui.toastArea, {
        level: "success",
        title: "Weiterleitung getestet",
        description: `Test erfolgreich, ${delivered} Request(s) zugestellt.`,
      });
      return;
    }
    if (delivered > 0 && failed > 0) {
      pushToast(ui.toastArea, {
        level: "info",
        title: "Test teilweise fehlgeschlagen",
        description: `${delivered} von ${delivered + failed} Requests zugestellt.`,
      });
      return;
    }
    const failureMsg = firstFailure?.http_status
      ? `Test fehlgeschlagen, HTTP ${firstFailure.http_status} von Zielsystem.`
      : firstFailure?.error
        ? `Test fehlgeschlagen, ${firstFailure.error}`
        : "Test fehlgeschlagen, Ziel nicht erreichbar.";
    pushToast(ui.toastArea, {
      level: "error",
      title: "Test fehlgeschlagen",
      description: failureMsg,
    });
  } catch (err) {
    state.lastForwardingTestResult = null;
    renderForwardingTestResult();
    pushToast(ui.toastArea, {
      level: "error",
      title: "Test fehlgeschlagen",
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

function renderSystemStatus(host = null) {
  const target = host || document.getElementById("settings-system-status");
  if (!target) return;
  const status = state.systemStatus || {};
  const uptime = Number(status.uptime_seconds || 0);
  const h = Math.floor(uptime / 3600);
  const m = Math.floor((uptime % 3600) / 60);
  const s = uptime % 60;
  const lastNasRun = status.last_nas_run_at ? new Date(status.last_nas_run_at).toLocaleString("de-DE") : "Noch kein Lauf";
  const lastNasError = status.last_nas_error || "Kein Fehler";
  target.innerHTML = `
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

function renderForwardingErrors(host = null) {
  const target = host || document.getElementById("settings-forwarding-errors");
  if (!target) return;
  const errors = state.forwardingErrors || [];
  const rows = errors.length
    ? errors
        .map(
          (entry) =>
            `<div class="list-item"><span>${new Date(entry.time).toLocaleString("de-DE")}</span><small>${entry.message}</small></div>`,
        )
        .join("")
    : `<div class="list-item"><span>Keine Forwarding-Fehler</span></div>`;
  target.innerHTML = `
    <div class="panel-head">
      <div class="panel-actions">
        <button data-action="reload-forwarding-errors" class="btn">Neu laden</button>
        <button data-action="clear-forwarding-errors" class="btn">Leeren</button>
      </div>
    </div>
    <div class="list">${rows}</div>
  `;
  const btn = target.querySelector('[data-action="reload-forwarding-errors"]');
  btn?.addEventListener("click", async () => {
    setButtonLoading(btn, true, "Lädt...");
    try {
      await loadForwardingErrors();
      renderForwardingErrors(target);
    } finally {
      setButtonLoading(btn, false);
    }
  });
  const clearBtn = target.querySelector('[data-action="clear-forwarding-errors"]');
  clearBtn?.addEventListener("click", async () => {
    setButtonLoading(clearBtn, true, "Löscht...");
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
      const title = entry.device_name || entry.device_id || "Unbekannt";
      const ts = entry.timestamp ? new Date(entry.timestamp).toLocaleString("de-DE") : "—";
      const parts = [
        `${entry.latitude}, ${entry.longitude}`,
        entry.accuracy != null ? `acc ${entry.accuracy}` : null,
        entry.device != null && entry.device !== "" ? `Client: ${entry.device}` : null,
        entry.battery != null && entry.battery !== "" ? `Batt ${entry.battery}` : null,
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
        <button data-action="reload-recent-gps" class="btn">Neu laden</button>
      </div>
    </div>
    <div class="list">${rows || `<div class="list-item"><span>Keine GPS-Daten</span></div>`}</div>
  `;
  const btn = target.querySelector('[data-action="reload-recent-gps"]');
  btn?.addEventListener("click", async () => {
    setButtonLoading(btn, true, "Lädt...");
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
