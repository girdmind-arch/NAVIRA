import { useCallback, useEffect, useState } from "react";
import { EmptyState, Icon, Notice, PageHeading } from "../components/ui";
import { reportsApi } from "../services/api";

const choices = ["Lighting", "Harassment", "Road hazard", "Crowding", "Other"];

export default function CommunityReports() {
  const [reports, setReports] = useState([]);
  const [category, setCategory] = useState(choices[0]);
  const [description, setDescription] = useState("");
  const [locality, setLocality] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const load = useCallback(async () => {
    setLoadingList(true);
    try { setReports(await reportsApi.list()); setError(""); }
    catch (requestError) { setError(requestError.message); }
    finally { setLoadingList(false); }
  }, []);

  useEffect(() => {
    let active = true;
    reportsApi.list()
      .then((items) => { if (active) { setReports(items); setError(""); } })
      .catch((requestError) => { if (active) setError(requestError.message); })
      .finally(() => { if (active) setLoadingList(false); });
    return () => { active = false; };
  }, []);

  async function submit(event) {
    event.preventDefault(); setError(""); setSuccess("");
    if (!locality.trim()) { setError("Enter a broad locality name. Do not enter coordinates or an exact address."); return; }
    setBusy(true);
    try {
      await reportsApi.create({
        category: category.toLowerCase(),
        description: description.trim(),
        approximate_geography: locality.trim(),
        expires_days: 7,
      });
      setDescription("");
      await load();
      setSuccess("Report submitted as unverified community information. It expires after seven days.");
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  }

  return <>
    <PageHeading eyebrow="COMMUNITY-SUBMITTED INFORMATION" title="Community Reports" description="Browse and submit short-lived, unverified reports using a broad locality name. The backend does not provide location-based filtering or moderation." action={<span className="status-chip status-chip--amber">Unverified reports</span>}/>
    <div className="reports-layout">
      <section className="panel report-form-panel">
        <div className="panel-heading"><div><p className="eyebrow">SHARE A LOCAL NOTE</p><h2>Submit a report</h2></div><span className="soft-icon tone-pink"><Icon name="report" size={19}/></span></div>
        <form className="stack-form" onSubmit={submit}>
          <label htmlFor="report-category">Category</label>
          <select id="report-category" value={category} onChange={(event) => setCategory(event.target.value)}>{choices.map((choice) => <option key={choice}>{choice}</option>)}</select>
          <label htmlFor="report-locality">Approximate locality</label>
          <input id="report-locality" value={locality} onChange={(event) => setLocality(event.target.value)} minLength={2} maxLength={100} required placeholder="e.g. Connaught Place" />
          <p className="form-helper">Use a broad area name only. The backend rejects coordinates and exact street addresses.</p>
          <label htmlFor="report-description">What would you like others to know?</label>
          <textarea id="report-description" rows="5" minLength={1} maxLength={500} required value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Keep the description factual and avoid personal details."/>
          <div className="field-count">{description.length}/500 characters</div>
          <button className="button button--primary button--wide" type="submit" disabled={busy}>{busy ? "Submitting…" : <><Icon name="plus" size={17}/> Submit report</>}</button>
        </form>
        {error && <Notice kind="error">{error}</Notice>}
        {success && <Notice kind="success">{success}</Notice>}
        <div className="report-review-note"><Icon name="shield" size={16}/><p>Reports are unverified and automatically expire. Do not include names, phone numbers, or other personal details.</p></div>
      </section>
      <section className="panel reports-list-panel">
        <div className="panel-heading"><div><p className="eyebrow">CURRENTLY ACTIVE</p><h2>Recent community reports</h2></div><button className="button button--secondary button--compact" onClick={load} disabled={loadingList}>{loadingList ? "Refreshing…" : "Refresh list"}</button></div>
        {loadingList && <div className="loading-state"><span className="spinner"/> Loading reports…</div>}
        {!loadingList && reports.length === 0 && <EmptyState icon="report" title="No active reports">The backend returned no active community reports.</EmptyState>}
        {!loadingList && reports.length > 0 && <div className="reports-list">{reports.map((report) => <article className="report-row" key={report.id}><span className="report-marker"><Icon name="report" size={17}/></span><div className="report-row__main"><div><strong>{report.category}</strong><span className="status-chip status-chip--amber">{report.status || "unverified"}</span></div><p>{report.description}</p><small><Icon name="pin" size={13}/> {report.geography || "Locality not provided"} · expires {new Date(report.expires_at).toLocaleString()}</small></div></article>)}</div>}
        <div className="report-list-note"><Icon name="shield" size={16}/> The list is not filtered by distance. Review each report's approximate locality and expiry time.</div>
      </section>
    </div>
  </>;
}
