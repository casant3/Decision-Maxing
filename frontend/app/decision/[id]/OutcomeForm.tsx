"use client";

import { useState } from "react";
import { api } from "@/lib/api";

// Outcome review: feeds the evaluation loop with real results.
export function OutcomeForm({ caseId }: { caseId: string }) {
  const [outcome, setOutcome] = useState("");
  const [rating, setRating] = useState(4);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!outcome.trim() || busy) return;
    setBusy(true);
    try {
      await api.recordOutcome(caseId, {
        review_date: new Date().toISOString().slice(0, 10),
        user_reported_outcome: outcome.trim(),
        usefulness_rating: rating,
      });
      setSaved(true);
    } finally {
      setBusy(false);
    }
  }

  if (saved) {
    return (
      <div className="card">
        <p className="note">Outcome recorded — thank you. This feeds the council&apos;s evaluation loop.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>How did it go?</h2>
      <p className="note">Come back later and record what actually happened.</p>
      <div className="field-row">
        <input
          type="text"
          placeholder="What happened after following (or ignoring) the recommendation?"
          value={outcome}
          onChange={(e) => setOutcome(e.target.value)}
        />
        <select value={rating} onChange={(e) => setRating(Number(e.target.value))} style={{ maxWidth: 180 }}>
          {[5, 4, 3, 2, 1].map((n) => (
            <option key={n} value={n}>
              Usefulness: {n}/5
            </option>
          ))}
        </select>
      </div>
      <button onClick={submit} disabled={busy || !outcome.trim()}>
        Record outcome
      </button>
    </div>
  );
}
