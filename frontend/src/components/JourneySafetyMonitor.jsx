import { useCallback, useEffect, useRef, useState } from "react";
import { Icon, Notice } from "./ui";
import { contactsApi, safetyApi } from "../services/api";
import { DEFAULT_SAFETY_CONFIG, createStationaryDetector, escalationStep, journeySafetyApi, offlineSosMessage } from "../services/journeySafety";

const TICK_MS = 1000;

function statusLabel(status) {
  if (status === "accepted_by_provider") return "Sent to SMS provider";
  if (status === "failed") return "Sending failed";
  if (status === "server_unreachable") return "Not sent: NAVIRA server unreachable";
  return "Not sent automatically (no SMS service configured)";
}

/**
 * Runs only while a journey is in progress: sends heartbeats, detects 5 minutes without movement,
 * shows up to three safety-check alerts, and raises SOS on "I Need Help" or no response.
 */
export default function JourneySafetyMonitor({ journey, fix }) {
  const [config, setConfig] = useState(DEFAULT_SAFETY_CONFIG);
  const [phase, setPhase] = useState("monitoring"); // monitoring | checking | sos
  const [alertNumber, setAlertNumber] = useState(0);
  const [sos, setSos] = useState(null);
  const [connectionIssue, setConnectionIssue] = useState("");
  const [sosError, setSosError] = useState("");
  const [savedContacts, setSavedContacts] = useState([]);
  const sosRef = useRef(null);
  const [stationaryDetector] = useState(() => createStationaryDetector({ durationMs: DEFAULT_SAFETY_CONFIG.stationary_minutes * 60000 }));
  const fixRef = useRef(null);
  const phaseRef = useRef("monitoring");
  const checkStartedAt = useRef(0);
  const sosInFlight = useRef(false);
  const lastFreshRequest = useRef(0);
  const lastSosBeat = useRef(0);
  const journeyId = journey.id;

  const enterPhase = useCallback((next) => { phaseRef.current = next; setPhase(next); }, []);
  const storeSos = useCallback((value) => { sosRef.current = value; setSos(value); }, []);
  const pendingSosReason = useRef(null);

  const deliverSos = useCallback(async (reason) => {
    if (sosInFlight.current || sosRef.current) return;
    sosInFlight.current = true;
    pendingSosReason.current = reason;
    try {
      storeSos(await journeySafetyApi.sos(journeyId, reason));
      pendingSosReason.current = null;
      setSosError("");
    } catch (error) {
      setSosError(`NAVIRA could not reach its server to alert your contacts (${error.message}). Text your contacts below or call 112.`);
    } finally {
      sosInFlight.current = false;
    }
  }, [journeyId, storeSos]);

  const sendHeartbeat = useCallback(async () => {
    const latest = fixRef.current;
    try {
      const result = await journeySafetyApi.heartbeat(journeyId, {
        ...(latest ? { latitude: latest.latitude, longitude: latest.longitude, accuracy_m: latest.accuracy, location_at: new Date(latest.timestamp).toISOString() } : {}),
        app_origin: window.location.origin,
      });
      setConnectionIssue("");
      if (result?.config) setConfig((current) => ({ ...current, ...result.config }));
      if (result?.active_sos) {
        // Raised by the server (for example after missed heartbeats), another tab, or this one.
        if (sosRef.current?.id !== result.active_sos.id) storeSos(result.active_sos);
        if (phaseRef.current !== "sos") enterPhase("sos");
      } else if (phaseRef.current === "sos" && !sosRef.current) {
        if (pendingSosReason.current) deliverSos(pendingSosReason.current); // SOS started while offline: deliver it now
      }
    } catch {
      setConnectionIssue("NAVIRA cannot reach its server. If the connection stays down during this journey, NAVIRA will alert your trusted contacts with your last known location and its time.");
    }
  }, [journeyId, enterPhase, storeSos, deliverSos]);

  const triggerSOS = useCallback((reason) => {
    if (sosInFlight.current || sosRef.current || phaseRef.current === "sos") return;
    enterPhase("sos");
    try { safetyApi.recordSOS().catch(() => { /* the journey SOS is the primary record */ }); } catch { /* existing SOS record is best effort */ }
    deliverSos(reason);
  }, [enterPhase, deliverSos]);

  // Keep trusted contacts on hand so SMS drafts work even if the server becomes unreachable.
  useEffect(() => {
    let active = true;
    try {
      contactsApi.list().then((items) => { if (active && Array.isArray(items)) setSavedContacts(items); }).catch(() => {});
    } catch { /* contacts stay unavailable offline */ }
    return () => { active = false; };
  }, []);

  // Feed GPS fixes into the stationary detector; during SOS push the latest position promptly.
  useEffect(() => {
    if (!fix) return;
    fixRef.current = fix;
    stationaryDetector.update(fix);
    if (phaseRef.current === "sos" && fix.timestamp - lastSosBeat.current >= 10000) {
      lastSosBeat.current = fix.timestamp;
      sendHeartbeat();
    }
  }, [fix, sendHeartbeat, stationaryDetector]);

  // Heartbeats to the backend while the journey is active.
  useEffect(() => {
    const first = setTimeout(sendHeartbeat, 0);
    const timer = setInterval(sendHeartbeat, config.heartbeat_interval_s * 1000);
    return () => { clearTimeout(first); clearInterval(timer); };
  }, [sendHeartbeat, config.heartbeat_interval_s]);

  // Stationary check and alert escalation clock.
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now();
      if (phaseRef.current === "monitoring") {
        const status = stationaryDetector.status(now);
        if (status.needsFreshFix && navigator.geolocation && now - lastFreshRequest.current > 60000) {
          lastFreshRequest.current = now;
          navigator.geolocation.getCurrentPosition(({ coords }) => {
            const fresh = { latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy, timestamp: Date.now() };
            fixRef.current = fresh;
            stationaryDetector.update(fresh);
          }, () => { /* without a fresh fix we cannot confirm the user is stationary */ }, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
        }
        if (status.stationary) {
          checkStartedAt.current = now;
          setAlertNumber(1);
          enterPhase("checking");
          navigator.vibrate?.([400, 200, 400]);
        }
      } else if (phaseRef.current === "checking") {
        const step = escalationStep(now - checkStartedAt.current, config.safety_check_window_s * 1000, config.safety_check_alerts);
        if (step.sosDue) triggerSOS("no_response_to_safety_checks");
        else setAlertNumber((current) => {
          if (step.alert > current) navigator.vibrate?.([400, 200, 400]);
          return Math.max(current, step.alert);
        });
      }
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [config.safety_check_window_s, config.safety_check_alerts, enterPhase, triggerSOS, stationaryDetector]);

  function confirmSafe() {
    stationaryDetector.reset(Date.now(), fixRef.current && { ...fixRef.current, timestamp: Date.now() });
    setAlertNumber(0);
    enterPhase("monitoring");
  }

  function needHelp() {
    triggerSOS("user_requested_help");
    window.location.href = "tel:112";
  }

  async function resolveSOS() {
    try {
      await journeySafetyApi.resolve(journeyId);
      storeSos(null);
      pendingSosReason.current = null;
      stationaryDetector.reset(Date.now(), fixRef.current && { ...fixRef.current, timestamp: Date.now() });
      enterPhase("monitoring");
    } catch (error) {
      setSosError(`Could not mark the SOS resolved: ${error.message}`);
    }
  }

  const message = sos?.message || offlineSosMessage(fix);
  const contacts = sos?.notifications?.contacts
    || savedContacts.map((contact) => ({ contact_id: contact.id, name: contact.name, phone: contact.phone, status: "server_unreachable" }));

  return <>
    {connectionIssue && phase !== "sos" && <Notice kind="warning">{connectionIssue}</Notice>}
    {phase === "checking" && <div className="modal-backdrop" role="presentation"><section className="confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="safety-check-title">
      <span className="confirm-icon"><Icon name="bell" size={25}/></span>
      <p className="eyebrow">SAFETY CHECK {alertNumber} OF {config.safety_check_alerts}</p>
      <h2 id="safety-check-title">You've been stationary for 5 minutes. Are you safe?</h2>
      <p>If you do not respond to {config.safety_check_alerts} safety checks, NAVIRA will automatically start SOS and alert your trusted contacts.</p>
      <div className="modal-actions"><button className="button button--secondary" type="button" onClick={confirmSafe}>I'm Safe</button><button className="button button--sos" type="button" onClick={needHelp}>I Need Help</button></div>
    </section></div>}
    {phase === "sos" && <section className="panel emergency-section" role="alert" aria-labelledby="auto-sos-title">
      <div className="emergency-heading"><div><p className="eyebrow">SOS ACTIVE</p><h2 id="auto-sos-title">{sos?.reason === "connectivity_lost" ? "SOS started after NAVIRA lost connection with this phone" : "SOS started"}</h2><p>{message}</p></div><span className="emergency-badge"><Icon name="shield" size={18}/> SOS</span></div>
      {sosError && <Notice kind="warning">{sosError}</Notice>}
      {!sos && !sosError && <p className="muted-copy" role="status">Starting SOS…</p>}
      {sos && <p className="form-helper">Live location link (updates while this phone has GPS and connectivity): <a href={sos.live_link} target="_blank" rel="noreferrer">{sos.live_link}</a></p>}
      {(sos || sosError) && (contacts.length === 0
        ? <p className="form-helper">No trusted contacts are saved, so nobody could be alerted. Add contacts in Profile &amp; Settings.</p>
        : <div className="safety-contact-list">{contacts.map((contact) => <div className="safety-contact-row" key={contact.contact_id}><span><strong>{contact.name}</strong><small>{statusLabel(contact.status)}</small></span>{contact.status !== "accepted_by_provider" && <a className="button button--secondary" href={`sms:${encodeURIComponent(contact.phone)}?body=${encodeURIComponent(message)}`}>Text {contact.name}</a>}</div>)}</div>)}
      {sos?.notifications?.police && <p className="form-helper">{sos.notifications.police.detail}</p>}
      <div className="modal-actions"><a className="button button--sos" href="tel:112"><Icon name="phone" size={16}/> Call 112</a>{sos && <button className="button button--secondary" type="button" onClick={resolveSOS}>I'm safe now — end SOS</button>}</div>
    </section>}
  </>;
}
