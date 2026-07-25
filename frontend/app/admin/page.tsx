"use client";

import { FormEvent, useState } from "react";
import { API_BASE, GuardianLensApiError } from "@/lib/api";

interface Bundle {
  label: string;
  is_active: boolean;
  development_stub: boolean;
  component_versions: Record<string, string>;
  band_boundaries: Record<string, number> | null;
}

interface RecordRow {
  assessment_id: string;
  title: string;
  band: string | null;
  score: number | null;
  status: string;
  created_at: string;
}

export default function AdminPage() {
  const [token, setToken] = useState("");
  const [bundles, setBundles] = useState<Bundle[]>([]);
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const headers = { "X-Admin-Token": token };
      const [bundleResponse, recordResponse] = await Promise.all([
        fetch(`${API_BASE}/api/v1/admin/bundles`, { headers, credentials: "include" }),
        fetch(`${API_BASE}/api/v1/admin/records`, { headers, credentials: "include" }),
      ]);
      if (!bundleResponse.ok) {
        const payload = await bundleResponse.json();
        throw new GuardianLensApiError(bundleResponse.status, payload);
      }
      if (!recordResponse.ok) {
        const payload = await recordResponse.json();
        throw new GuardianLensApiError(recordResponse.status, payload);
      }
      setBundles(await bundleResponse.json());
      setRecords(await recordResponse.json());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Admin data could not be loaded.");
    }
  }

  function exportUrl(dataset: "outputs" | "study") {
    return `${API_BASE}/api/v1/admin/export?dataset=${dataset}`;
  }

  return (
    <main className="page page-wide">
      <p className="eyebrow">Research administration</p>
      <h1 className="page-title">GuardianLens admin</h1>
      <p className="page-lead">The first draft uses a development token gate. Replace it with Supabase Auth and role checks before Gate D.</p>

      <form className="card" onSubmit={load}>
        <div className="field">
          <label htmlFor="admin-token">Development admin token</label>
          <input id="admin-token" type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" />
        </div>
        {error && <p className="error-text">{error}</p>}
        <button className="button button-primary" disabled={!token}>Load administration data</button>
      </form>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Model bundles</h2>
        {bundles.length === 0 ? <p>No bundle data loaded.</p> : (
          <div className="table-wrap"><table><thead><tr><th>Label</th><th>Active</th><th>Components</th><th>Boundaries</th></tr></thead><tbody>
            {bundles.map((bundle) => <tr key={bundle.label}><td className="code">{bundle.label}</td><td>{bundle.is_active ? "Yes" : "No"}{bundle.development_stub ? " (stub)" : ""}</td><td>{Object.entries(bundle.component_versions).map(([key, value]) => <div key={key}><strong>{key}</strong>: {value}</div>)}</td><td className="code">{bundle.band_boundaries ? JSON.stringify(bundle.band_boundaries) : "Pending"}</td></tr>)}
          </tbody></table></div>
        )}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Anonymised assessment records</h2>
        {records.length === 0 ? <p>No records loaded.</p> : (
          <div className="table-wrap"><table><thead><tr><th>Created</th><th>Title</th><th>Status</th><th>Score</th><th>Band</th></tr></thead><tbody>
            {records.map((record) => <tr key={record.assessment_id}><td>{new Date(record.created_at).toLocaleString()}</td><td>{record.title}</td><td>{record.status}</td><td>{record.score ?? ""}</td><td>{record.band ?? ""}</td></tr>)}
          </tbody></table></div>
        )}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Exports</h2>
        <p>Use an authenticated API request in the final implementation. Direct links below are placeholders because browsers cannot attach the development token header to a normal download link.</p>
        <p className="code">{exportUrl("outputs")}</p>
        <p className="code">{exportUrl("study")}</p>
      </section>
    </main>
  );
}
