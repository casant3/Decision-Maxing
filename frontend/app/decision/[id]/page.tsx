"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, CaseStatusInfo, ResultPayload } from "@/lib/api";
import { CouncilRoom } from "./CouncilRoom";
import { RerunForm } from "./RerunForm";
import { OutcomeForm } from "./OutcomeForm";

interface Turn {
  role: string;
  content: string;
}

export default function DecisionPage({ params }: { params: { id: string } }) {
  const caseId = params.id;
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const [status, setStatus] = useState<CaseStatusInfo | null>(null);
  const [result, setResult] = useState<ResultPayload | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([api.detail(caseId), api.status(caseId)]);
      setDetail(d);
      setStatus(s);
      if (s.status === "complete") {
        api.result(caseId).then(setResult).catch(() => undefined);
      }
      return s.status;
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load");
      return "error";
    }
  }, [caseId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const s = await refresh();
      if (s !== "running" && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 1500);
  }, [refresh]);

  useEffect(() => {
    if (status?.status === "running") startPolling();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status?.status, startPolling]);

  async function send() {
    if (!message.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.sendMessage(caseId, message.trim());
      setMessage("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to send");
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    setBusy(true);
    setError("");
    try {
      await api.run(caseId);
      await refresh();
      startPolling();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to start");
    } finally {
      setBusy(false);
    }
  }

  if (!detail || !status) {
    return <div className="card">{error ? <span>{error}</span> : "Loading…"}</div>;
  }

  const turns: Turn[] = (detail.conversation as Turn[]) ?? [];
  const caseStatus = status.status;

  return (
    <>
      <div className="card">
        <h2>{String(detail.title ?? "Decision")}</h2>
        <div className="chat">
          {turns.map((t, i) => (
            <div key={i} className={`bubble ${t.role === "user" ? "user" : "assistant"}`}>
              {t.content}
            </div>
          ))}
        </div>

        {caseStatus === "intake" && (
          <div className="composer">
            <textarea
              value={message}
              placeholder="Your answer…"
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
              }}
            />
            <button onClick={send} disabled={busy || !message.trim()}>
              Send
            </button>
          </div>
        )}

        {caseStatus === "ready" && (
          <button onClick={run} disabled={busy}>
            Convene the council
          </button>
        )}
        {error && <p className="note" style={{ color: "var(--danger)" }}>{error}</p>}
      </div>

      {(caseStatus === "running" || caseStatus === "complete" || caseStatus === "failed") &&
        status.stages.length > 0 && (
          <div className="card">
            <h2>{caseStatus === "running" ? "Working on it" : "Process"}</h2>
            <ul className="stage-list">
              {status.stages.map((s) => (
                <li key={s.stage} className={s.status}>
                  <span className="dot" />
                  {s.label}
                  {s.status === "skipped" && <span className="note">(skipped)</span>}
                </li>
              ))}
            </ul>
            {status.degradations.length > 0 && (
              <div className="warnbox">
                {status.degradations.map((d, i) => (
                  <div key={i}>{d}</div>
                ))}
              </div>
            )}
          </div>
        )}

      {caseStatus === "failed" && (
        <div className="card">
          <h2>This run hit a problem</h2>
          <p className="note">
            {(detail.workflow as any)?.failures?.join("; ") || "Unknown failure."}
          </p>
          <button onClick={run} disabled={busy}>
            Resume run
          </button>
        </div>
      )}

      {caseStatus === "complete" && result && (
        <ResultView result={result} detail={detail} />
      )}

      {caseStatus === "complete" && (
        <>
          <CouncilRoom detail={detail} />
          <RerunForm caseId={caseId} onRerun={() => { setResult(null); refresh().then(startPolling); }} />
          <OutcomeForm caseId={caseId} />
        </>
      )}
    </>
  );
}

function ResultView({
  result,
  detail,
}: {
  result: ResultPayload;
  detail: Record<string, any>;
}) {
  const r = result.response;
  return (
    <div className="card">
      <div className="rec">{r.recommendation}</div>

      {result.validation && !result.validation.valid && (
        <div className="warnbox">
          The plan has unresolved constraint issues:{" "}
          {result.validation.defects.map((d) => d.description).join("; ")}
        </div>
      )}

      <h3>Why this direction won</h3>
      <p style={{ whiteSpace: "pre-wrap" }}>{r.why_this_won}</p>

      {r.council_disagreements.length > 0 && (
        <>
          <h3>What the council disagreed about</h3>
          <ul className="tight">
            {r.council_disagreements.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </>
      )}

      {r.immediate_next_action && (
        <>
          <h3>Immediate next action</h3>
          <p>{r.immediate_next_action}</p>
        </>
      )}

      {r.seven_day_plan.length > 0 && (
        <>
          <h3>Seven-day plan</h3>
          <ul className="tight">
            {r.seven_day_plan.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </>
      )}

      {r.test_and_success_criteria.length > 0 && (
        <>
          <h3>Test &amp; success criteria</h3>
          <ul className="tight">
            {r.test_and_success_criteria.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </>
      )}

      {r.main_risks.length > 0 && (
        <>
          <h3>Main risks</h3>
          <ul className="tight">
            {r.main_risks.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </>
      )}

      {r.assumptions_and_unknowns.length > 0 && (
        <>
          <h3>Assumptions &amp; unknowns</h3>
          <ul className="tight">
            {r.assumptions_and_unknowns.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </>
      )}

      <h3>Confidence</h3>
      <p className="note">{r.confidence_explanation}</p>
    </div>
  );
}
