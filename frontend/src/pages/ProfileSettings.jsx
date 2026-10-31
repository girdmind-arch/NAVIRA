import { useEffect, useState } from "react";
import { PageHeading, Notice, EmptyState, GirlIllustration, Icon } from "../components/ui";
import { authApi, contactsApi, journeysApi, profileApi, setToken } from "../services/api";
import {
  countries,
  getEditablePhone,
  getPreferredCountry,
  getSavedPhoneNumber,
  validatePhoneNumber,
} from "../services/phoneNumbers";

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "Not recorded";
}

function formatDistance(meters) {
  return Number.isFinite(meters) ? `${(meters / 1000).toFixed(1)} km` : "Unavailable";
}

export default function ProfileSettings({ authenticated, setAuthenticated, onAuthenticated, onSignOut, authNotice = "", theme }) {
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [contactName, setContactName] = useState("");
  const [phone, setPhone] = useState("");
  const [country, setCountry] = useState(() => getPreferredCountry());
  const [phoneError, setPhoneError] = useState("");
  const [relationship, setRelationship] = useState("Trusted contact");
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!authenticated) return undefined;
    let active = true;
    Promise.all([profileApi.get(), journeysApi.history(), contactsApi.list()])
      .then(([account, journeys, trustedContacts]) => {
        if (!active) return;
        setProfile(account);
        setName(account.name);
        setCountry(getPreferredCountry(account));
        setHistory(journeys);
        setContacts(trustedContacts);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      });
    return () => { active = false; };
  }, [authenticated]);

  async function authenticate(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = mode === "login"
        ? await authApi.login(email.trim(), password)
        : await authApi.register(email.trim(), password, name.trim());
      setToken(null);
      setProfile(payload.user);
      setPassword("");
      setAuthenticated(true);
      onAuthenticated?.();
    } catch (requestError) {
      if (mode === "register" && /already exists/i.test(requestError.message)) {
        setMode("login");
        setPassword("");
        setMessage("An account with this email already exists. Please sign in with your existing password.");
        setError("");
      } else {
        setError(requestError.message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile(event) {
    event.preventDefault();
    try {
      const updated = await profileApi.update({ name: name.trim() });
      setProfile(updated);
      setMessage("Profile updated.");
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function saveContact(event) {
    event.preventDefault();
    setPhoneError("");
    setBusy(true);
    setError("");
    try {
      const validatedPhone = await validatePhoneNumber(phone, country);
      if (validatedPhone.error) {
        setPhoneError(validatedPhone.error);
        return;
      }
      const duplicate = contacts.some((contact) => (
        contact.id !== editing
        && getSavedPhoneNumber(contact.phone, country) === validatedPhone.number
      ));
      if (duplicate) {
        setPhoneError("This phone number is already saved as a trusted contact.");
        return;
      }
      const data = {
        name: contactName.trim(),
        phone: validatedPhone.number,
        relationship_label: relationship.trim() || "Trusted contact",
      };
      const saved = editing
        ? await contactsApi.update(editing, data)
        : await contactsApi.create(data);
      setContacts((items) => editing
        ? items.map((item) => item.id === saved.id ? saved : item)
        : [...items, saved]);
      setContactName("");
      setPhone("");
      setPhoneError("");
      setRelationship("Trusted contact");
      setEditing(null);
      setMessage("Trusted contact saved.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeContact(id) {
    if (!window.confirm("Remove this trusted contact?")) return;
    try {
      await contactsApi.remove(id);
      setContacts((items) => items.filter((item) => item.id !== id));
      setMessage("Trusted contact removed.");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  if (!authenticated) {
    return <div className="landing-grid">
      <section className="landing-intro auth-hero">
        <p className="eyebrow">SAFER STEPS. BRIGHTER TOMORROWS.</p>
        <h1>Navigate freely. Move confidently.</h1>
        <p className="landing-lede">Plan a route with clear context, share your location by choice, and stay connected to people you trust.</p>
        <GirlIllustration theme={theme} className="landing-journey-illustration" alt="Girl walking along a winding path through a soft pink city landscape"/>
        <button className="button button--primary landing-route-cta" type="button" onClick={() => setMode("register")}>Plan your first route <Icon name="arrow" size={16}/></button>
        <div className="landing-features">
          <div><span className="quick-icon tone-lavender"><Icon name="route" size={19}/></span><span><strong>Thoughtful route planning</strong><small>Compare road options and see what the evidence can—and cannot—say.</small></span></div>
          <div><span className="quick-icon tone-pink"><Icon name="compass" size={19}/></span><span><strong>Journey Companion</strong><small>Continue with your saved route and record your journey when you choose.</small></span></div>
          <div><span className="quick-icon tone-blue"><Icon name="shield" size={19}/></span><span><strong>Your safety workspace</strong><small>Manage trusted contacts and temporary location sharing from one place.</small></span></div>
        </div>
        <p className="landing-disclaimer">NAVIRA provides journey awareness tools, not emergency dispatch or a guarantee of safety.</p>
      </section>
      <section className="panel landing-auth">
        <div className="panel-heading">
          <div><p className="eyebrow">YOUR NAVIRA ACCOUNT</p><h2>{mode === "login" ? "Sign in to continue" : "Create your account"}</h2></div>
          <span className="profile-avatar"><Icon name="user" size={25}/></span>
        </div>
        <div className="auth-tabs" role="tablist" aria-label="Account options">
          <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "is-active" : ""} onClick={() => setMode("login")}>Sign in</button>
          <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "is-active" : ""} onClick={() => setMode("register")}>Create account</button>
        </div>
        {authNotice && <Notice kind="warning">{authNotice}</Notice>}
        {message && <Notice kind="success">{message}</Notice>}
        <form className="stack-form" onSubmit={authenticate}>
          {mode === "register" && <>
            <label htmlFor="account-name">Your name</label>
            <input id="account-name" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} autoComplete="name"/>
          </>}
          <label htmlFor="account-email">Email address</label>
          <input id="account-email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)}/>
          <label htmlFor="account-password">Password</label>
          <input id="account-password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={8} maxLength={200} value={password} onChange={(event) => setPassword(event.target.value)}/>
          <button className="button button--primary button--wide" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
        </form>
        {error && <Notice kind="error">{error}</Notice>}
        <p className="muted-copy landing-auth-note">Your password is processed by NAVIRA's account service and is never stored in this browser.</p>
      </section>
    </div>;
  }

  const heading = <PageHeading
    eyebrow="YOUR ACCOUNT"
    title="Profile & Journey History"
    description="Manage your profile, completed journeys, and private trusted contacts."
    action={<button className="button button--secondary" onClick={onSignOut}><Icon name="logout" size={16}/> Sign out</button>}
  />;

  return <>
    {heading}
    {error && <Notice kind="error">{error}</Notice>}
    {message && <Notice kind="success">{message}</Notice>}
    <div className="profile-grid">
      <section className="panel profile-account">
        <div className="panel-heading"><div><p className="eyebrow">USER PROFILE</p><h2>Account details</h2></div><span className="profile-avatar"><Icon name="user" size={25}/></span></div>
        <form className="stack-form" onSubmit={saveProfile}>
          <label htmlFor="profile-name">Name</label>
          <input id="profile-name" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)}/>
          <label htmlFor="profile-email">Email</label>
          <input id="profile-email" value={profile?.email || email} readOnly/>
          <button className="button button--primary">Save profile</button>
        </form>
      </section>
      <section className="panel contacts-panel">
        <div className="panel-heading"><div><p className="eyebrow">EMERGENCY SUPPORT</p><h2>Trusted contacts</h2><p className="panel-subtitle">Private to your signed-in account. NAVIRA does not send messages or place calls.</p></div></div>
        <form className="contact-form" onSubmit={saveContact}>
          <label htmlFor="contact-name">Name</label>
          <input id="contact-name" required maxLength={100} value={contactName} onChange={(event) => setContactName(event.target.value)} placeholder="Trusted person"/>
          <label htmlFor="contact-phone">Phone number</label>
          <div className="contact-phone-input">
            <select id="contact-country" required value={country} onChange={(event) => { setCountry(event.target.value); setPhoneError(""); }} aria-label="Country and dialing code">
              <option value="">Select a country</option>
              {countries.map((option) => <option key={option.code} value={option.code}>
                {option.flag} {option.name} +{option.callingCode}
              </option>)}
            </select>
            <input id="contact-phone" type="tel" required maxLength={32} autoComplete="tel-national" value={phone} onChange={(event) => { setPhone(event.target.value); setPhoneError(""); }} placeholder="Enter phone number" aria-describedby={phoneError ? "contact-phone-error" : undefined}/>
          </div>
          <label htmlFor="contact-relationship">Relationship</label>
          <input id="contact-relationship" maxLength={60} value={relationship} onChange={(event) => setRelationship(event.target.value)}/>
          <button className="button button--primary button--wide" disabled={busy}>{editing ? "Update contact" : "Add trusted contact"}</button>
          {editing && <button type="button" className="button button--secondary button--wide" onClick={() => { setEditing(null); setContactName(""); setPhone(""); setPhoneError(""); setRelationship("Trusted contact"); }}>Cancel edit</button>}
        </form>
        {phoneError && <div id="contact-phone-error"><Notice kind="error">{phoneError}</Notice></div>}
        {contacts.map((contact) => <div className="saved-contact" key={contact.id}>
          <span className="avatar avatar--small">{contact.name[0]?.toUpperCase()}</span>
          <span><strong>{contact.name}</strong><small>{contact.relationship_label} · {contact.phone}</small></span>
          <div><button onClick={() => { const editablePhone = getEditablePhone(contact.phone, country); setEditing(contact.id); setContactName(contact.name); setCountry(editablePhone.country || ""); setPhone(editablePhone.value); setPhoneError(""); setRelationship(contact.relationship_label); }}>Edit</button><button onClick={() => removeContact(contact.id)}>Remove</button></div>
        </div>)}
        {!contacts.length && <p className="muted-copy">No trusted contacts yet.</p>}
      </section>
    </div>
    <section className="panel contacts-panel">
      <div className="panel-heading"><div><p className="eyebrow">JOURNEY HISTORY</p><h2>Completed journeys</h2></div></div>
      {history.length ? <div className="saved-contacts">{history.map((journey) => <article className="saved-contact journey-history-row" key={journey.id}>
        <span className="glance-icon tone-lavender"><Icon name="route" size={17}/></span>
        <span><strong>{journey.origin} → {journey.destination}</strong><small>Journey date: {formatDate(journey.completed_at || journey.planned_at)}</small><small>Started: {formatDate(journey.started_at)} · Completed: {formatDate(journey.completed_at)}</small><small>Route: {journey.route_id} · {formatDistance(journey.route?.distance_m)} · Total time: {journey.started_at && journey.completed_at ? Math.max(0, Math.round((new Date(journey.completed_at) - new Date(journey.started_at)) / 60000)) + " min" : "Unavailable"}</small></span>
        <span className="status-chip status-chip--green">Completed</span>
      </article>)}</div> : <EmptyState icon="route" title="No completed journeys yet">Only journeys you start and mark complete appear here.</EmptyState>}
    </section>
  </>;
}
