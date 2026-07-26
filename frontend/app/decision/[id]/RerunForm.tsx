"use client";

import { useState } from "react";
import { api } from "@/lib/api";

// Change a constraint and selectively rerun only the affected stages.
export function RerunForm({ caseId, onRerun }: { caseId: string; onRerun: () => void }) {
  const [kind, setKind] = useState("budget");
  const [description, setDescription] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!description.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.changeConstraint(caseId, {
        kind,
        description: description.trim(),
        value: value.trim() || null,
        hard: true,
      });
      onRerun();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>Changed circumstances?</h2>
      <p className="note">
        Update a constraint and the council reruns only the stages it affects —
        existing research is kept.
      </p>
      <div className="field-row">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="budget">Budget</option>
          <option value="time">Available time</option>
          <option value="deadline">Deadline</option>
          <option value="skill">Skills</option>
          <option value="other">Other</option>
        </select>
        <input
          type="text"
          placeholder="Constraint description (e.g. total budget)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <input
          type="text"
          placeholder="Value (e.g. $2,000 or 5 h/week)"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </div>
      <button onClick={submit} disabled={busy || !description.trim()}>
        {busy ? "Rerunning…" : "Update and rerun"}
      </button>
      {error && <p className="note" style={{ color: "var(--danger)" }}>{error}</p>}
    </div>
  );
}
