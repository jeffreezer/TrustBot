"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./lib/api";
import type { QuestionnaireSummary } from "./lib/types";

export default function Home() {
  const [items, setItems] = useState<QuestionnaireSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.listQuestionnaires();
      setItems(data.questionnaires);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load questionnaires");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onUpload = useCallback(async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await api.upload(file);
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [load]);

  return (
    <div className="page">
      <header className="appbar">
        <h1 className="brand">TrustBot</h1>
        <span className="tagline">Evidence-backed questionnaire responder · review workspace</span>
      </header>

      <section className="panel">
        <h2>Upload a questionnaire</h2>
        <p className="muted">
          CSV or Excel, one question per row. A sample lives at{" "}
          <code>seed/northwind_ai/questionnaires/Inbound_Security_Questionnaire.csv</code>.
        </p>
        <div className="uploadRow">
          <input ref={fileRef} type="file" accept=".csv,.tsv,.xlsx,.xls" />
          <button className="btn primary" onClick={onUpload} disabled={uploading}>
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </section>

      {error && <p className="bad banner">{error}</p>}

      <section className="panel">
        <h2>Questionnaires</h2>
        {items === null ? (
          <p className="muted">Loading…</p>
        ) : items.length === 0 ? (
          <p className="muted">None yet — upload one to begin.</p>
        ) : (
          <table className="qtable">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Progress</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((q) => (
                <tr key={q.id}>
                  <td>{q.title}</td>
                  <td>
                    <span className={`pill ${q.status}`}>{q.status}</span>
                  </td>
                  <td className="muted">
                    {q.answered_count} / {q.question_count} drafted
                  </td>
                  <td>
                    <Link className="btn" href={`/questionnaires/${q.id}`}>
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
