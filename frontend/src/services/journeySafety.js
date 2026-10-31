import { api, request } from "./api";

export const SOS_MESSAGE_TEMPLATE = "SOS EMERGENCY! I am in danger and need immediate help. My current location is: [Live Location Link]. Please help me immediately!";

export const DEFAULT_SAFETY_CONFIG = {
  stationary_minutes: 5,
  safety_check_alerts: 3,
  safety_check_window_s: 180,
  heartbeat_interval_s: 30,
  missed_heartbeats: 4,
};

export const journeySafetyApi = {
  state: (journeyId) => request(`/api/journeys/${journeyId}/safety`),
  heartbeat: (journeyId, body) => request(`/api/journeys/${journeyId}/safety/heartbeat`, "POST", body, { keepalive: true }),
  sos: (journeyId, reason) => request(`/api/journeys/${journeyId}/safety/sos`, "POST", { reason }, { keepalive: true }),
  resolve: (journeyId) => request(`/api/journeys/${journeyId}/safety/sos/resolve`, "POST"),
  live: (token) => api(`/api/v1/journey-sos/live/${encodeURIComponent(token)}`, { auth: false }),
};

export function sosMessage(link) {
  return SOS_MESSAGE_TEMPLATE.replace("[Live Location Link]", link);
}

/** Message used only when NAVIRA's server cannot be reached; SMS drafts can still go out over the cellular network. */
export function offlineSosMessage(fix) {
  if (!fix) return sosMessage("unavailable (no GPS fix yet)");
  const link = `https://www.openstreetmap.org/?mlat=${fix.latitude.toFixed(6)}&mlon=${fix.longitude.toFixed(6)}#map=17/${fix.latitude.toFixed(6)}/${fix.longitude.toFixed(6)}`;
  return `${sosMessage(link)} Last known location recorded at ${new Date(fix.timestamp).toLocaleString()}.`;
}

export function distanceMeters(a, b) {
  const radians = (degrees) => degrees * Math.PI / 180;
  const dLat = radians(b.latitude - a.latitude);
  const dLon = radians(b.longitude - a.longitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.latitude)) * Math.cos(radians(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

/**
 * GPS-noise tolerant stationary detector.
 * - Fixes worse than maxAccuracyM are ignored (they neither prove movement nor stillness).
 * - Movement needs `confirmFixes` consecutive fixes outside an accuracy-scaled radius around the anchor,
 *   so a single GPS jump cannot reset or fake the timer.
 * - "Stationary" is only reported with a fresh accurate fix; with stale GPS the caller should request one.
 */
export function createStationaryDetector({
  durationMs = 5 * 60 * 1000,
  maxAccuracyM = 100,
  minMoveM = 30,
  maxMoveM = 100,
  confirmFixes = 2,
  freshFixMs = 90 * 1000,
} = {}) {
  let anchor = null;
  let anchorAt = 0;
  let lastGoodAt = 0;
  let pending = 0;

  function threshold(fix) {
    return Math.min(maxMoveM, Math.max(minMoveM, 1.5 * ((anchor.accuracy || 0) + (fix.accuracy || 0))));
  }

  return {
    update(fix) {
      if (!fix || !Number.isFinite(fix.latitude) || !Number.isFinite(fix.longitude)) return "ignored";
      if (!Number.isFinite(fix.accuracy) || fix.accuracy > maxAccuracyM) return "ignored";
      lastGoodAt = fix.timestamp;
      if (!anchor) {
        anchor = fix; anchorAt = fix.timestamp; pending = 0;
        return "anchored";
      }
      if (distanceMeters(anchor, fix) > threshold(fix)) {
        pending += 1;
        if (pending >= confirmFixes) {
          anchor = fix; anchorAt = fix.timestamp; pending = 0;
          return "moved";
        }
        return "possible-movement";
      }
      pending = 0;
      if (fix.accuracy < anchor.accuracy) anchor = { ...fix }; // refine position, keep the timer
      return "still";
    },
    status(now) {
      const stillForMs = anchor ? Math.max(0, now - anchorAt) : 0;
      const due = Boolean(anchor) && stillForMs >= durationMs;
      const fresh = now - lastGoodAt <= freshFixMs;
      return { stillForMs, stationary: due && fresh, needsFreshFix: due && !fresh };
    },
    reset(now, fix = null) {
      anchor = fix && Number.isFinite(fix.accuracy) && fix.accuracy <= maxAccuracyM ? { ...fix } : null;
      anchorAt = now; pending = 0;
      if (anchor) lastGoodAt = fix.timestamp;
    },
  };
}

/** Pure escalation step: which safety-check alert (1..n) is due and whether SOS is due. */
export function escalationStep(elapsedMs, windowMs, alerts = 3) {
  if (elapsedMs >= windowMs) return { alert: alerts, sosDue: true };
  return { alert: Math.min(alerts, Math.floor(elapsedMs / (windowMs / alerts)) + 1), sosDue: false };
}
