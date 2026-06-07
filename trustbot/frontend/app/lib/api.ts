// Typed client for the TrustBot review-workspace API.
import type {
  JobStatus,
  QuestionDetail,
  QuestionnaireDetail,
  QuestionnaireSummary,
  ReviewAction,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export type ReviewBody = {
  action: ReviewAction;
  edited_text?: string;
  comment?: string;
  reviewer?: string;
};

export const api = {
  listQuestionnaires: () =>
    request<{ questionnaires: QuestionnaireSummary[] }>("/questionnaires"),

  getQuestionnaire: (id: string) =>
    request<QuestionnaireDetail>(`/questionnaires/${id}`),

  getQuestion: (id: string) => request<QuestionDetail>(`/questions/${id}`),

  // Starts a background job; returns immediately with the job id (202).
  generate: (id: string, regenerate = false) =>
    request<{ job_id: string }>(`/questionnaires/${id}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ regenerate }),
    }),

  getJob: (jobId: string) => request<JobStatus>(`/jobs/${jobId}`),

  review: (answerId: string, body: ReviewBody) =>
    request<{ answer_id: string; review_status: string; needs_human_review: boolean }>(
      `/answers/${answerId}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),

  upload: (file: File) =>
    request<{ id: string; title: string; status: string }>(
      `/questionnaires?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      },
    ),

  exportUrl: (id: string, format: "csv" | "xlsx") =>
    `${API_URL}/questionnaires/${id}/export?format=${format}`,

  // Absolute URL for an org-scoped, audited document download (server gives a relative path).
  documentUrl: (path: string) => `${API_URL}${path}`,
};
