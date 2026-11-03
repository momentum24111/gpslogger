import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  isClosedHistoricalRange,
  keepPreviousRouteEndpoint,
  livePositionRouteAction,
} from "../static/route-live-rules.js";

const now = new Date("2026-11-03T12:00:00+01:00");
const appSource = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");

assert.equal(appSource.includes("refreshMapData({ preserveView: true, background: true })"), false);

assert.equal(isClosedHistoricalRange("custom", "2026-08-31", now), true);
assert.equal(isClosedHistoricalRange("custom", "2026-11-03", now), false);
assert.equal(isClosedHistoricalRange("6h", "2026-08-31", now), false);

assert.equal(keepPreviousRouteEndpoint(0, 10), true);
assert.equal(keepPreviousRouteEndpoint(21, 10), true);
assert.equal(keepPreviousRouteEndpoint(25, 10), false);
assert.equal(keepPreviousRouteEndpoint(30, 1), true);

const base = {
  now,
  deviceVisible: true,
  duplicate: false,
  timestamp: "2026-11-03T11:00:00+01:00",
  loading: false,
};

assert.equal(livePositionRouteAction({
  ...base,
  range: "custom",
  customTo: "2026-08-31",
  rangeFrom: "2026-08-01T00:00:00.000Z",
  rangeTo: "2026-08-31T21:59:59.999Z",
}), "ignore");

assert.equal(livePositionRouteAction({
  ...base,
  range: "6h",
  rangeFrom: "2026-11-03T05:00:00+01:00",
  rangeTo: "2026-11-03T12:00:00+01:00",
}), "append");

assert.equal(livePositionRouteAction({
  ...base,
  range: "6h",
  deviceVisible: false,
  rangeFrom: "2026-11-03T05:00:00+01:00",
  rangeTo: "2026-11-03T12:00:00+01:00",
}), "ignore");

assert.equal(livePositionRouteAction({
  ...base,
  range: "6h",
  duplicate: true,
  rangeFrom: "2026-11-03T05:00:00+01:00",
  rangeTo: "2026-11-03T12:00:00+01:00",
}), "ignore");

assert.equal(livePositionRouteAction({
  ...base,
  range: "current",
}), "marker");

assert.equal(livePositionRouteAction({
  ...base,
  range: "24h",
  loading: true,
  rangeFrom: "2026-11-02T12:00:00+01:00",
  rangeTo: "2026-11-03T12:00:00+01:00",
}), "ignore");

console.log("route-live-rules ok");
