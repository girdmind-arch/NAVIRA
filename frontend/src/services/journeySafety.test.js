import { describe, expect, it } from "vitest";
import { createStationaryDetector, escalationStep, offlineSosMessage, sosMessage } from "./journeySafety";

const MIN = 60000;
const base = { latitude: 28.6139, longitude: 77.209 };
const offset = (meters) => ({ ...base, latitude: base.latitude + meters / 111320 });

describe("stationary detector", () => {
  it("reports stationary after 5 minutes of GPS jitter within the accuracy radius", () => {
    const detector = createStationaryDetector();
    for (let t = 0; t <= 5 * MIN; t += 15000) {
      detector.update({ ...offset((t / 15000) % 2 ? 18 : -12), accuracy: 20, timestamp: t });
    }
    expect(detector.status(5 * MIN).stationary).toBe(true);
  });

  it("does not let a single GPS jump reset the timer, but confirmed movement does", () => {
    const detector = createStationaryDetector();
    detector.update({ ...base, accuracy: 10, timestamp: 0 });
    expect(detector.update({ ...offset(400), accuracy: 10, timestamp: 2 * MIN })).toBe("possible-movement");
    expect(detector.update({ ...base, accuracy: 10, timestamp: 2.2 * MIN })).toBe("still");
    expect(detector.status(5 * MIN + 1).stillForMs).toBeGreaterThanOrEqual(5 * MIN);
    detector.update({ ...offset(200), accuracy: 10, timestamp: 4 * MIN });
    expect(detector.update({ ...offset(240), accuracy: 10, timestamp: 4.2 * MIN })).toBe("moved");
    expect(detector.status(5 * MIN).stationary).toBe(false);
  });

  it("ignores inaccurate fixes and requires a fresh fix before declaring stationary", () => {
    const detector = createStationaryDetector();
    expect(detector.update({ ...base, accuracy: 900, timestamp: 0 })).toBe("ignored");
    detector.update({ ...base, accuracy: 15, timestamp: 0 });
    const status = detector.status(6 * MIN);
    expect(status.stationary).toBe(false);
    expect(status.needsFreshFix).toBe(true);
    detector.update({ ...base, accuracy: 15, timestamp: 6 * MIN });
    expect(detector.status(6 * MIN).stationary).toBe(true);
  });

  it("restarts the 5-minute timer on reset (user confirmed safe)", () => {
    const detector = createStationaryDetector();
    detector.update({ ...base, accuracy: 10, timestamp: 0 });
    detector.reset(5 * MIN, { ...base, accuracy: 10, timestamp: 5 * MIN });
    expect(detector.status(6 * MIN).stationary).toBe(false);
    detector.update({ ...base, accuracy: 10, timestamp: 10 * MIN });
    expect(detector.status(10 * MIN).stationary).toBe(true);
  });
});

describe("escalation and messages", () => {
  it("spreads three alerts across the response window and then makes SOS due", () => {
    expect(escalationStep(0, 180000)).toEqual({ alert: 1, sosDue: false });
    expect(escalationStep(60000, 180000)).toEqual({ alert: 2, sosDue: false });
    expect(escalationStep(120000, 180000)).toEqual({ alert: 3, sosDue: false });
    expect(escalationStep(180000, 180000)).toEqual({ alert: 3, sosDue: true });
  });

  it("uses the exact SOS wording", () => {
    expect(sosMessage("https://x/#/live/abc")).toBe("SOS EMERGENCY! I am in danger and need immediate help. My current location is: https://x/#/live/abc. Please help me immediately!");
    expect(offlineSosMessage({ ...base, accuracy: 5, timestamp: 0 })).toContain("Last known location recorded at");
  });
});
