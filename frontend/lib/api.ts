// Thin typed client for the Decision Council backend. All rendering of
// server/model text goes through React's default escaping — never inject HTML.

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface CaseSummary {
  case_id: string;
  title: string;
  status: string;
  version: number;
  updated_at: string;
}

export interface IntakeReply {
  case_id: string;
  status: string;
  assistant_message: string;
  version: number;
}

export interface StageInfo {
  stage: string;
  label: string;
  status: string;
}

export interface CaseStatusInfo {
  case_id: string;
  status: string;
  version: number;
  route: string | null;
  stages: StageInfo[];
  cost_usd: number;
  degradations: string[];
}

export interface UserFacingResponse {
  recommendation: string;
  why_this_won: string;
  council_disagreements: string[];
  immediate_next_action: string;
  seven_day_plan: string[];
  test_and_success_criteria: string[];
  main_risks: string[];
  assumptions_and_unknowns: string[];
  confidence_explanation: string;
}

export interface ResultPayload {
  case_id: string;
  response: UserFacingResponse;
  validation: { valid: boolean; defects: { code: string; description: string }[] } | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listCases: () => request<CaseSummary[]>("/api/cases"),
  createCase: (message: string) =>
    request<IntakeReply>("/api/cases", { method: "POST", body: JSON.stringify({ message }) }),
  sendMessage: (caseId: string, message: string) =>
    request<IntakeReply>(`/api/cases/${caseId}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  run: (caseId: string) => request<{ status: string }>(`/api/cases/${caseId}/run`, { method: "POST" }),
  status: (caseId: string) => request<CaseStatusInfo>(`/api/cases/${caseId}/status`),
  result: (caseId: string) => request<ResultPayload>(`/api/cases/${caseId}/result`),
  detail: (caseId: string) => request<Record<string, unknown>>(`/api/cases/${caseId}`),
  changeConstraint: (caseId: string, constraint: Record<string, unknown>) =>
    request<{ status: string; invalidated_stages: string[] }>(`/api/cases/${caseId}/constraints`, {
      method: "POST",
      body: JSON.stringify({ constraint }),
    }),
  recordOutcome: (caseId: string, review: Record<string, unknown>) =>
    request<{ status: string }>(`/api/cases/${caseId}/outcome`, {
      method: "POST",
      body: JSON.stringify(review),
    }),
};
