import { useCallback, useEffect, useState } from "react";
import { Icon, Notice, PageHeading } from "../components/ui";
import { backendApi, contactsApi, safetyApi } from "../services/api";

function getDeviceLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("This browser does not support location access."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({
        latitude: coords.latitude,
        longitude: coords.longitude,
        accuracy_m: coords.accuracy,
      }),
      () => reject(new Error("Location permission was denied or the device location is unavailable.")),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  });
}

function formatTime(value) {
  return new Date(value).toLocaleString();
}

function getDialUri(phone) {
  const rawNumber = String(phone || "").trim();
  if (!/^\+?[0-9\s().-]+$/.test(rawNumber)) return null;
  const dialNumber = rawNumber.replace(/[^\d+]/g, "");
  const digitCount = dialNumber.replace(/\D/g, "").length;
  return digitCount >= 7 && digitCount <= 15 && /^\+?\d+$/.test(dialNumber)
    ? `tel:${dialNumber}`
    : null;
}

const helplines = [
  { number: "112", name: "All-in-one emergency response", group: "Emergency services", note: "Pan-India emergency response number.", source: "https://112.gov.in/" },
  { number: "108", name: "Ambulance / emergency medical service", group: "Medical emergency", note: "Ambulance coverage and dispatch arrangements vary by state/UT.", source: "https://nhm.gov.in/" },
  { number: "181", name: "Women Helpline", group: "Women support", note: "Women’s Helpline service availability and referral arrangements may vary by state/UT.", source: "https://wcd.gov.in/" },
  { number: "1091", name: "Women Police Helpline", group: "Women support", note: "Police helpline coverage and operation are state/UT-specific; use 112 for an immediate emergency.", source: "https://delhipolice.gov.in/" },
  { number: "1930", name: "Cybercrime financial fraud helpline", group: "Cybercrime", note: "For reporting cyber financial fraud; also file a report through the National Cyber Crime Reporting Portal.", source: "https://cybercrime.gov.in/Webform/Helpline.aspx" },
  { number: "1098", name: "Child Helpline", group: "Child protection", note: "Child-protection helpline; state/UT response and referral arrangements may vary.", source: "https://missionshakti.wcd.gov.in/" },
];

export default function SafetyCenter({ pendingSOS, onSOSReady }) {
  const [resource, setResource] = useState(null);
  const [resourceError, setResourceError] = useState("");
  const [safetyError, setSafetyError] = useState("");
  const [contactsError, setContactsError] = useState("");
  const [notice, setNotice] = useState("");
  const [contacts, setContacts] = useState([]);
  const [contactsLoading, setContactsLoading] = useState(true);
  const [shares, setShares] = useState([]);
  const [shareLink, setShareLink] = useState("");
  const [busy, setBusy] = useState(false);
  const confirming = pendingSOS;

  const refreshSafetyData = useCallback(async () => {
    const shareResult = await safetyApi.shares();
    setShares(shareResult.items || []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    backendApi.emergencyResources()
      .then((data) => { if (!cancelled) setResource(data); })
      .catch((requestError) => { if (!cancelled) setResourceError(requestError.message); });
    safetyApi.status()
      .then(() => {
        if (!cancelled) return refreshSafetyData();
        return undefined;
      })
      .catch((requestError) => { if (!cancelled) setSafetyError(requestError.message); });
    contactsApi.list()
      .then((result) => {
        if (!Array.isArray(result)) throw new Error("The trusted contacts response was invalid.");
        if (!cancelled) {
          setContacts(result);
          setContactsError("");
        }
      })
      .catch((requestError) => { if (!cancelled) setContactsError(requestError.message); })
      .finally(() => { if (!cancelled) setContactsLoading(false); });
    return () => { cancelled = true; };
  }, [refreshSafetyData]);

  function closeConfirm() { onSOSReady?.(false); }

  function continueToCall() {
    closeConfirm();
    setBusy(true);
    setSafetyError("");
    safetyApi.recordSOS()
      .then(() => {
        setNotice("Your SOS request was recorded by NAVIRA. No contacts or emergency services were notified automatically.");
      })
      .catch((requestError) => setSafetyError(`NAVIRA could not record the SOS request: ${requestError.message}`))
      .finally(() => setBusy(false));
    window.location.href = resource?.dial_uri || "tel:112";
  }

  async function createLocationShare() {
    setBusy(true);
    setSafetyError("");
    setNotice("");
    try {
      const location = await getDeviceLocation();
      const share = await safetyApi.createShare({ ...location, expires_minutes: 60 });
      const link = `${window.location.origin}/#/share/${share.token}`;
      setShareLink(link);
      await refreshSafetyData();
      setNotice("A one-hour location snapshot link is ready. It updates only when you create another share.");
    } catch (requestError) {
      setSafetyError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function revokeShare(share) {
    setBusy(true);
    setSafetyError("");
    try {
      await safetyApi.revokeShare(share.id);
      setShares((items) => items.filter((item) => item.id !== share.id));
      setShareLink("");
      setNotice("Location link revoked. It can no longer display your location.");
    } catch (requestError) {
      setSafetyError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function copyShareLink() {
    try {
      await navigator.clipboard.writeText(shareLink);
      setNotice("Location link copied. Send it only to someone you trust.");
    } catch {
      setSafetyError("Copy was blocked by the browser. Select and copy the link from the field.");
    }
  }

  return <>
    <PageHeading eyebrow="EMERGENCY RESOURCES" title="Location Sharing" description="Manage trusted contacts, share a temporary location snapshot, and find official emergency helplines."/>
    {resourceError && <Notice kind="warning">{resourceError} You can still call 112 in India if you need urgent help.</Notice>}
    {safetyError && <Notice kind="warning">{safetyError}</Notice>}
    {notice && <Notice kind="info">{notice}</Notice>}

    <section className="sharing-section panel">
      <div className="panel-heading"><div><p className="eyebrow">LOCATION SHARING</p><h2>Share a temporary location</h2><p className="panel-subtitle">Create a private one-hour link to your current location. This is a single snapshot, not continuous tracking.</p></div><span className="soft-icon tone-lavender"><Icon name="pin" size={20}/></span></div>
      <div className="privacy-callout"><Icon name="shield" size={16}/><p>Your location is requested only after you choose to share it. NAVIRA stores the snapshot until the link expires or you revoke it; recipients with the link can view it.</p></div>
      <div className="safety-actions"><button className="button button--primary" type="button" onClick={createLocationShare} disabled={busy}>{busy ? "Please wait…" : "Share my current location"}</button></div>
      {shareLink && <div className="share-token"><label htmlFor="location-share-link">Temporary location link</label><div><input id="location-share-link" value={shareLink} readOnly/><button className="button button--secondary" type="button" onClick={copyShareLink}>Copy link</button></div>
        {contacts.length > 0 && <div className="share-contact-actions">{contacts.map((contact) => <a className="button button--secondary" key={contact.id} href={`sms:${encodeURIComponent(contact.phone)}?body=${encodeURIComponent(`Please check on me. My temporary location is: ${shareLink}`)}`}>Text {contact.name}</a>)}</div>}
        <small>Opening a text creates a draft on your device. NAVIRA does not send messages.</small></div>}
      {shares.length > 0 && <div className="active-shares"><strong>Active links</strong>{shares.map((share) => <div className="active-share-row" key={share.id}><span>Expires {formatTime(share.expires_at)}</span><button className="text-button" type="button" onClick={() => revokeShare(share)} disabled={busy}>Revoke</button></div>)}</div>}
    </section>

    <section className="panel safety-contacts-section">
      <div className="panel-heading"><div><p className="eyebrow">TRUSTED CONTACTS</p><h2>Your emergency contacts</h2><p className="panel-subtitle">Contacts are tied to your signed-in account. They are never notified automatically.</p></div><span className="soft-icon tone-pink"><Icon name="user" size={19}/></span></div>
      {contactsError && <Notice kind="warning">Could not load your trusted contacts: {contactsError}</Notice>}
      {contactsLoading ? <p className="muted-copy" role="status">Loading trusted contacts…</p> : contacts.length === 0 ? <p className="muted-copy">No trusted contacts added yet. Add contacts in <a href="#/profile">Profile &amp; Settings</a>.</p> : <div className="safety-contact-list">{contacts.map((contact) => {
        const dialUri = getDialUri(contact.phone);
        return <div className="safety-contact-row" key={contact.id}><span><strong>{contact.name}</strong>{dialUri ? <a className="safety-contact-phone" href={dialUri}>{contact.phone}</a> : <small>{contact.phone || "Phone number unavailable"} · Cannot dial this number; update it in <a href="#/profile">Profile &amp; Settings</a>.</small>}</span>{dialUri && <a className="safety-contact-call button button--secondary" href={dialUri} aria-label={`Call ${contact.name}`} title={`Open dialer for ${contact.name}`}><Icon name="phone" size={16}/> Call</a>}</div>;
      })}</div>}
    </section>

    <section className="panel emergency-section" aria-labelledby="location-sos-title">
      <div className="emergency-heading">
        <div><p className="eyebrow">EMERGENCY SOS</p><h2 id="location-sos-title">Need urgent help?</h2><p>Open your phone dialer after confirming. NAVIRA does not place calls or alert contacts automatically.</p></div>
        <span className="emergency-badge"><Icon name="shield" size={18}/> Confirmation required</span>
      </div>
      <div className="emergency-content">
        <article className="emergency-card">
          <span className="sos-symbol"><Icon name="phone" size={21}/></span>
          <div><strong>Call emergency services</strong><p>India emergency response. Confirm the call in your device dialer.</p></div>
          <button className="button button--sos" type="button" onClick={() => onSOSReady?.(true)}>Open SOS confirmation · {resource?.number || "112"}</button>
        </article>
        <p className="emergency-disclaimer"><Icon name="report" size={16}/><span>Your location and trusted contacts are not sent when you open the dialer. Call availability is determined by your phone and network.</span></p>
      </div>
    </section>

    <section className="panel emergency-helplines" aria-labelledby="emergency-helplines-title">
      <div className="panel-heading"><div><p className="eyebrow">INDIA HELPLINES</p><h2 id="emergency-helplines-title">Emergency Helplines</h2><p className="panel-subtitle">Tap a number or call button to open your device dialer. You must confirm the call there.</p></div><span className="emergency-badge"><Icon name="phone" size={17}/> Call options</span></div>
      <div className="helpline-grid">{helplines.map((helpline) => <article className={`helpline-card helpline-card--${helpline.group.toLowerCase().replaceAll(" ", "-")}`} key={helpline.number}>
        <div className="helpline-card__heading"><span><small>{helpline.group}</small><strong>{helpline.name}</strong></span><a className="helpline-number" href={`tel:${helpline.number}`} aria-label={`Call ${helpline.number}, ${helpline.name}`}>{helpline.number}</a></div>
        <p>{helpline.note}</p>
        <div className="helpline-card__actions"><a className="button button--secondary" href={`tel:${helpline.number}`}><Icon name="phone" size={16}/> Call {helpline.number}</a><a href={helpline.source} target="_blank" rel="noreferrer">Official information</a></div>
      </article>)}</div>
      <div className="emergency-disclaimer"><Icon name="report" size={16}/><p>Helpline numbers and service coverage may change or differ by state/UT. NAVIRA opens your phone dialer; it does not place or confirm calls.</p></div>
    </section>
    {confirming && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeConfirm(); }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-sos-title"><button className="modal-close icon-button" onClick={closeConfirm} aria-label="Close"><Icon name="close"/></button><span className="confirm-icon"><Icon name="bell" size={25}/></span><p className="eyebrow">PLEASE CONFIRM</p><h2 id="confirm-sos-title">Record an SOS request and open your phone?</h2><p>NAVIRA will record the request, then open your dialer for {resource?.number || "112"}. It will not place the call or alert contacts automatically.</p><div className="modal-actions"><button className="button button--secondary" onClick={closeConfirm}>Cancel</button><button className="button button--sos" onClick={continueToCall}>Continue</button></div></section></div>}
  </>;
}
