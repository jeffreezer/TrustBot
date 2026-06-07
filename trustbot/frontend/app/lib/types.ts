// Shared API response shapes (mirrors the FastAPI review-workspace endpoints).

export type QuestionnaireSummary = {
  id: string;
  title: string;
  status: string;
  source_format: string | null;
  question_count: number;
  answered_count: number;
  created_at: string | null;
};

export type QuestionRow = {
  id: string;
  external_id: string | null;
  domain: string | null;
  text: string;
  row_index: number | null;
  answer_id: string | null;
  status: string;
  outcome: string | null;
  confidence: string | null;
  needs_human_review: boolean | null;
};

export type JobStatusValue = "pending" | "running" | "done" | "failed";

export type ActiveJob = {
  job_id: string;
  status: JobStatusValue;
  total: number;
  completed: number;
};

export type QuestionnaireDetail = {
  id: string;
  title: string;
  status: string;
  source_format: string | null;
  active_job: ActiveJob | null;
  questions: QuestionRow[];
};

export type JobStatus = {
  job_id: string;
  status: JobStatusValue;
  total: number;
  completed: number;
  error: string | null;
};

export type EvidenceRef = {
  chunk_id: string;
  source_type: string;
  source_id: string | null;
  title: string | null;
};

export type ProvidedDocument = {
  document_id: string;
  title: string | null;
  download_url: string;
};

export type CandidateDocument = {
  document_id: string;
  title: string | null;
  document_kind: string | null;
};

export type Finding = {
  id: string;
  external_ref: string | null;
  title: string | null;
  severity: string | null;
  status: string;
  identified_date: string | null;
  target_remediation_date: string | null;
  remediated_date: string | null;
  remediation_summary: string | null;
};

export type AnswerPayload = {
  id: string;
  mode: string | null;
  outcome: string | null;
  short_answer: string | null;
  answer: string | null;
  claim: string | null;
  scope: string | null;
  requires_document: boolean | null;
  provided_documents: ProvidedDocument[];
  document_selection_required: boolean | null;
  candidate_documents: CandidateDocument[];
  remediation_required: boolean | null;
  findings: Finding[];
  confidence: string | null;
  needs_human_review: boolean | null;
  review_reason: string | null;
  review_status: string;
  freshness_status: string | null;
  evidence_refs: EvidenceRef[];
  generated_by: string | null;
};

export type Citation = {
  chunk_id: string;
  source_type: string;
  title: string | null;
  text: string;
  confidentiality: string | null;
  customer_shareable: boolean | null;
};

export type QuestionDetail = {
  question: {
    id: string;
    external_id: string | null;
    domain: string | null;
    text: string;
  };
  answer: AnswerPayload | null;
  citations: Citation[];
};

export type ReviewAction =
  | "approve"
  | "edit"
  | "reject"
  | "request_evidence"
  | "save_to_library";
