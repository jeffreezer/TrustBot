"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Health = {
  status: string;
  service: string;
  env: string;
  database: string;
};

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then((data: Health) => setHealth(data))
      .catch(() => setError("API unreachable"));
  }, []);

  const apiOk = health?.status === "ok";
  const dbOk = health?.database === "connected";

  return (
    <main>
      <div className="card">
        <h1 className="title">TrustBot</h1>
        <p className="subtitle">
          Evidence-backed AI security questionnaire responder — Phase 0
        </p>

        {error && <p className="bad">{error}</p>}

        <div className="row">
          <span>Frontend</span>
          <span className="ok">
            <span className="dot ok" />
            running
          </span>
        </div>

        <div className="row">
          <span>API</span>
          <span className={health ? (apiOk ? "ok" : "bad") : ""}>
            <span className={`dot ${health ? (apiOk ? "ok" : "bad") : ""}`} />
            {health ? health.status : "checking…"}
          </span>
        </div>

        <div className="row">
          <span>Database</span>
          <span className={health ? (dbOk ? "ok" : "bad") : ""}>
            <span className={`dot ${health ? (dbOk ? "ok" : "bad") : ""}`} />
            {health ? health.database : "checking…"}
          </span>
        </div>
      </div>
    </main>
  );
}
