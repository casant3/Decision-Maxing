"use client";

// Expandable "Council Room": advisor responses, chairman scores, evidence,
// audit findings. Hidden by default so the main answer stays uncluttered.

export function CouncilRoom({ detail }: { detail: Record<string, any> }) {
  const advisors: any[] = detail.advisor_runs ?? [];
  const amap = detail.argument_map;
  const draft = detail.chairman_draft;
  const final = detail.chairman_final;
  const audit = detail.audit;
  const evidence: any[] = detail.evidence?.items ?? [];

  if (!final && advisors.length === 0) return null;

  return (
    <div className="card">
      <details className="council">
        <summary>Open the Council Room</summary>

        {advisors.length > 0 && (
          <>
            <h3>Advisor recommendations</h3>
            <div className="advisor-grid">
              {advisors.map((run) => (
                <div className="advisor" key={run.anonymous_id}>
                  <div className="lens">
                    {String(run.response.role).replace(/_/g, " ")}{" "}
                    <span className="conf">({run.anonymous_id}{run.failed ? " — failed, skipped" : ""})</span>
                  </div>
                  {!run.failed && (
                    <>
                      <p>{run.response.recommendation}</p>
                      <p className="conf">
                        Evidence confidence {Math.round(run.response.evidence_confidence * 100)}% ·
                        Reasoning confidence {Math.round(run.response.reasoning_confidence * 100)}%
                        {" · "}Cheapest test: {run.response.cheapest_useful_test || "—"}
                      </p>
                    </>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {final?.option_scores?.length > 0 && (
          <>
            <h3>Chairman scoring (weighted criteria)</h3>
            <table className="scores">
              <thead>
                <tr>
                  <th>Option</th>
                  <th>Weighted total</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {final.option_scores.map((o: any) => {
                  const total = (o.scores ?? []).reduce(
                    (acc: number, s: any) => acc + s.weight * s.score,
                    0
                  );
                  return (
                    <tr key={o.option_id}>
                      <td>{o.option_id}</td>
                      <td>{total.toFixed(2)}</td>
                      <td>
                        {(o.scores ?? [])
                          .map((s: any) => `${s.criterion}: ${s.score}`)
                          .join(", ")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}

        {amap?.disagreements?.length > 0 && (
          <>
            <h3>Disagreements preserved</h3>
            <ul className="tight">
              {amap.disagreements.map((d: string, i: number) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          </>
        )}

        {evidence.length > 0 && (
          <>
            <h3>Evidence ledger</h3>
            <ul className="tight">
              {evidence.map((e) => (
                <li key={e.claim_id}>
                  <strong>[{e.claim_id}]</strong> {e.claim}{" "}
                  <span className="note">
                    ({e.status}, confidence {Math.round((e.confidence ?? 0) * 100)}%
                    {e.source_title ? `, ${e.source_title}` : ""})
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}

        {audit && (
          <>
            <h3>Audit findings</h3>
            {(audit.defects ?? []).length === 0 ? (
              <p className="note">No defects raised.</p>
            ) : (
              <ul className="tight">
                {audit.defects.map((d: any, i: number) => (
                  <li key={i}>
                    <strong>{d.severity}:</strong> {d.description} — {d.required_correction}
                  </li>
                ))}
              </ul>
            )}
            {audit.premortem && (
              <p className="note">
                Pre-mortem — most likely failure: {audit.premortem.most_likely_failure_cause}
              </p>
            )}
            {draft && final && draft.decision !== final.decision && (
              <p className="note">
                The Chairman revised the draft after the audit (both versions are preserved).
              </p>
            )}
          </>
        )}
      </details>
    </div>
  );
}
