/** Entscheidet, ob ein Live-Ereignis die geladene Route neu laden oder nur erweitern darf. */

export function isClosedHistoricalRange(range, customToDate, now = new Date()) {
  if (range !== "custom" || !customToDate) return false;
  const end = new Date(`${customToDate}T23:59:59.999`);
  if (Number.isNaN(end.getTime())) return false;
  return end.getTime() < now.getTime();
}

/** Entspricht der serverseitigen Kartenausdünnung: jeder n-te Punkt und immer der letzte. */
export function keepPreviousRouteEndpoint(oldCount, stride) {
  const count = Number(oldCount) || 0;
  const step = Number(stride) || 1;
  if (count <= 0 || step <= 1) return true;
  return (count - 1) % step === 0;
}

export function livePositionRouteAction({
  range,
  customTo = "",
  deviceVisible = false,
  duplicate = false,
  timestamp = "",
  rangeFrom = "",
  rangeTo = "",
  loading = false,
  now = new Date(),
} = {}) {
  if (!deviceVisible || duplicate) return "ignore";
  if (range === "current") return "marker";
  if (loading || isClosedHistoricalRange(range, customTo, now)) return "ignore";
  const stamp = Date.parse(String(timestamp || ""));
  if (!Number.isFinite(stamp)) return "ignore";
  const fromMs = Date.parse(String(rangeFrom || ""));
  const toMs = Date.parse(String(rangeTo || ""));
  if (Number.isFinite(fromMs) && stamp < fromMs) return "ignore";
  if (range === "custom" && Number.isFinite(toMs) && stamp > toMs) return "ignore";
  return "append";
}
