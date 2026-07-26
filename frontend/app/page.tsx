"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, CaseSummary } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cases, setCases] = useState<CaseSummary[]>([]);

  useEffect(() => {
    api.listCases().then(setCases).catch(() => setCases([]));
  }, []);

  async function start() {
    if (!message.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const reply = await api.createCase(message.trim());
      router.push(`/decision/${reply.case_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card">
        <h2>What decision are you facing?</h2>
        <p className="note">
          Describe the decision, your goal, and any constraints you already know
          (budget, time, deadlines). The council asks follow-ups only when the
          answer would change its recommendation.
        </p>
        <div className="composer" style={{ marginTop: "0.75rem" }}>
          <textarea
            value={message}
            placeholder="e.g. Should I leave my job to go full-time on my side project?"
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) start();
            }}
          />
          <button onClick={start} disabled={busy || !message.trim()}>
            {busy ? "Starting…" : "Start"}
          </button>
        </div>
        {error && <p className="note" style={{ color: "var(--danger)" }}>{error}</p>}
      </div>

      <div className="card">
        <h2>Decision history</h2>
        {cases.length === 0 && <p className="note">No decisions yet.</p>}
        {cases.map((c) => (
          <div className="case-row" key={c.case_id}>
            <a href={`/decision/${c.case_id}`}>{c.title || c.case_id}</a>
            <span className={`badge ${c.status}`}>{c.status}</span>
          </div>
        ))}
      </div>
    </>
  );
}
