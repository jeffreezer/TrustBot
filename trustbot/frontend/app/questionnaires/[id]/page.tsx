"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../lib/api";
import type {
  Citation,
  JobStatus,
  QuestionDetail,
  QuestionnaireDetail,
  QuestionRow,
  ReviewAction,
} from "../../lib/types";

const REVIEWER_DEFAULT = "reviewer@demo";

function StatusPill({ status }: { status: string }) {
  return <span className={`pill ${status}`}>{status.replace(/_/g, " ")}</span>;
}

function OutcomeChip({ outcome }: { outcome: string | null }) {
  if (!outcome) return null;
  return <span className={`chip ${outcome}`}>{outcome.replace(/_/g, " ")}</span>;
}

function ConfidenceBadge({ confidence }: { confidence: string | null }) {
  if (!confidence) return null;
  return <span className={`conf ${confidence}`}>confidence: {confidence}</span>;
}

function CitationCard({ c }: { c: Citation }) {
  const snippet = c.text.length > 320 ? `${c.text.slice(0, 320)}…` : c.text;
  return (
    <div className="citation">
      <div className="citationHead">
        <span className={`src ${c.source_type}`}>{c.source_type}</span>
        <span className="citationTitle">{c.title || "(untitled)"}</span>
        {c.customer_shareable === false && <span className="pill rejected">internal</span>}
      </div>
      <p className="citationText">{snippet}</p>
    </div>
  );
}

export default function Workspace() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [detail, setDetail] = useState<QuestionnaireDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [qd, setQd] = useState<QuestionDetail | null>(null);
  const [editText, setEditText] = useState("");
  const [reviewer, setReviewer] = useState(REVIEWER_DEFAULT);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const selectedIdRef = useRef<string | null>(null);

  const loadDetail = useCallback(async () => {
    try {
      const d = await api.getQuestionnaire(id);
      setDetail(d);
      setError(null);
      // Resume a running job after a page refresh (don't clobber an in-flight poll).
      if (d.active_job) {
        const aj = d.active_job;
        setActiveJobId((cur) => cur ?? aj.job_id);
        setJob((cur) => cur ?? { ...aj, error: null });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load questionnaire");
    }
  }, [id]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const selectQuestion = useCallback(async (questionId: string) => {
    setSelectedId(questionId);
    selectedIdRef.current = questionId;
    setQd(null);
    setPicked([]);
    try {
      const data = await api.getQuestion(questionId);
      setQd(data);
      setEditText(data.answer?.answer ?? "");
      // Pre-select the recommended (cited) document so confirming is one click.
      setPicked(
        (data.answer?.candidate_documents ?? [])
          .filter((c) => c.recommended)
          .map((c) => c.document_id),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load question");
    }
  }, []);

  // Poll the active job every ~2s until it finishes; then refresh the answers. Survives a
  // refresh because activeJobId is re-derived from the questionnaire's active_job above.
  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const j = await api.getJob(activeJobId);
        if (cancelled) return;
        setJob(j);
        if (j.status === "done" || j.status === "failed") {
          setActiveJobId(null);
          if (j.status === "failed") setError(j.error || "Generation failed");
          else setMessage(`Drafted ${j.completed} / ${j.total}.`);
          await loadDetail();
          if (selectedIdRef.current) await selectQuestion(selectedIdRef.current);
          return;
        }
      } catch (e) {
        if (!cancelled) {
          setActiveJobId(null);
          setError(e instanceof Error ? e.message : "Lost contact with the job");
        }
        return;
      }
      if (!cancelled) setTimeout(tick, 2000);
    };
    void tick();
    return () => {
      cancelled = true;
    };
  }, [activeJobId, loadDetail, selectQuestion]);

  const generate = useCallback(
    async (regenerate: boolean) => {
      setError(null);
      setMessage(null);
      try {
        const { job_id } = await api.generate(id, regenerate);
        setJob({ job_id, status: "pending", total: 0, completed: 0, error: null });
        setActiveJobId(job_id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not start generation");
      }
    },
    [id],
  );

  const act = useCallback(
    async (action: ReviewAction) => {
      if (!qd?.answer) return;
      setBusy(true);
      setMessage(null);
      try {
        const r = await api.review(qd.answer.id, {
          action,
          reviewer,
          edited_text: action === "edit" ? editText : undefined,
        });
        setMessage(`Marked ${r.review_status}.`);
        await loadDetail();
        if (selectedId) await selectQuestion(selectedId);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusy(false);
      }
    },
    [qd, reviewer, editText, loadDetail, selectQuestion, selectedId],
  );

  const attachDocs = useCallback(async () => {
    if (!qd?.answer || picked.length === 0) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.attachDocuments(qd.answer.id, picked);
      setMessage(`Attached ${picked.length} document${picked.length > 1 ? "s" : ""}.`);
      setPicked([]);
      if (selectedId) await selectQuestion(selectedId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to attach documents");
    } finally {
      setBusy(false);
    }
  }, [qd, picked, selectQuestion, selectedId]);

  const answer = qd?.answer ?? null;
  const undrafted = detail?.questions.filter((q) => q.status === "undrafted").length ?? 0;
  const generating = job?.status === "pending" || job?.status === "running";
  const pct = job && job.total > 0 ? Math.round((job.completed / job.total) * 100) : 0;

  return (
    <div className="page">
      <header className="appbar">
        <div>
          <Link href="/" className="back">
            ← Questionnaires
          </Link>
          <h1 className="brand">{detail?.title ?? "Workspace"}</h1>
        </div>
        <div className="appbarActions">
          <button
            className="btn primary"
            onClick={() => void generate(undrafted === 0)}
            disabled={generating || busy}
          >
            {generating
              ? "Drafting…"
              : undrafted > 0
                ? `Generate ${undrafted} draft(s)`
                : "Regenerate all"}
          </button>
          <a className="btn" href={api.exportUrl(id, "csv")}>
            Export CSV
          </a>
          <a className="btn" href={api.exportUrl(id, "xlsx")}>
            Export Excel
          </a>
        </div>
      </header>

      {generating && (
        <div className="progress">
          <div className="progressLabel">
            Drafting… {job?.completed ?? 0} / {job?.total ?? 0}
          </div>
          <div className="progressTrack">
            <div className="progressBar" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}
      {error && <p className="bad banner">{error}</p>}
      {message && <p className="ok banner">{message}</p>}

      <div className="workspace">
        {/* LEFT — question list with statuses */}
        <aside className="pane list">
          {(detail?.questions ?? []).map((q: QuestionRow) => (
            <button
              key={q.id}
              className={`qitem ${q.id === selectedId ? "active" : ""}`}
              onClick={() => void selectQuestion(q.id)}
            >
              <div className="qitemTop">
                <span className="qid">{q.external_id || q.row_index}</span>
                <StatusPill status={q.status} />
              </div>
              <div className="qitemText">{q.text}</div>
              <div className="qitemMeta">
                <OutcomeChip outcome={q.outcome} />
                {q.needs_human_review && <span className="flag">needs review</span>}
              </div>
            </button>
          ))}
        </aside>

        {/* CENTER — selected question + editable draft */}
        <main className="pane center">
          {!qd ? (
            <p className="muted">Select a question on the left.</p>
          ) : (
            <>
              <div className="qhead">
                {qd.question.domain && <span className="domain">{qd.question.domain}</span>}
                <h2>{qd.question.text}</h2>
              </div>

              {!answer ? (
                <p className="muted">
                  No draft yet — use “Generate” above to draft an answer from evidence.
                </p>
              ) : (
                <>
                  <div className="answerMeta">
                    <OutcomeChip outcome={answer.outcome} />
                    <ConfidenceBadge confidence={answer.confidence} />
                    <StatusPill status={answer.review_status} />
                    {answer.freshness_status && (
                      <span className="muted">freshness: {answer.freshness_status}</span>
                    )}
                  </div>

                  {answer.injection_flagged && (
                    <div className="injectionBanner">
                      <strong>⚠ Prompt-injection content detected and neutralized.</strong>{" "}
                      The injected instruction was treated as inert data and never executed; the
                      answer is grounded in approved evidence and held for your review.
                    </div>
                  )}

                  {answer.needs_human_review && (
                    <div className="reviewBanner">
                      <strong>Needs human review.</strong>{" "}
                      {answer.review_reason || "The system could not fully support this answer."}
                    </div>
                  )}

                  {answer.sub_answers && answer.sub_answers.length > 0 && (
                    <div className="subAnswers">
                      <strong>Per-part breakdown</strong>
                      <ol>
                        {answer.sub_answers.map((s, i) => (
                          <li key={i}>
                            <div className="subQ">{s.sub_question}</div>
                            <div className="subMeta">
                              <span className={`outcome outcome-${s.outcome}`}>
                                {s.outcome}
                              </span>
                              {s.needs_human_review && (
                                <span className="needsReview">needs review</span>
                              )}
                              <span className="subCites">
                                {s.evidence_refs.length} citation
                                {s.evidence_refs.length === 1 ? "" : "s"}
                              </span>
                            </div>
                            {s.outcome === "needs_input" && (
                              <div className="subFlag">
                                {s.review_reason ||
                                  "No approved evidence substantiates this part."}
                              </div>
                            )}
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}

                  <label className="fieldLabel">Draft answer (editable)</label>
                  <textarea
                    className="answerBox"
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    rows={10}
                  />
                  {answer.document_selection_required && (
                    <div className="docPicker">
                      <strong>
                        Document selection required — choose the artifact(s) to attach:
                      </strong>
                      {answer.candidate_documents &&
                      answer.candidate_documents.length > 0 ? (
                        <>
                          <ul>
                            {answer.candidate_documents.map((c) => (
                              <li key={c.document_id}>
                                <label>
                                  <input
                                    type="checkbox"
                                    checked={picked.includes(c.document_id)}
                                    onChange={(e) =>
                                      setPicked((p) =>
                                        e.target.checked
                                          ? [...p, c.document_id]
                                          : p.filter((x) => x !== c.document_id),
                                      )
                                    }
                                  />
                                  {c.document_kind && (
                                    <span className="kind">{c.document_kind}</span>
                                  )}{" "}
                                  {c.title || "Document"}
                                  {c.recommended && (
                                    <span className="recommended">recommended</span>
                                  )}
                                </label>
                              </li>
                            ))}
                          </ul>
                          <button
                            type="button"
                            disabled={busy || picked.length === 0}
                            onClick={attachDocs}
                          >
                            Confirm attachment
                          </button>
                        </>
                      ) : (
                        <p className="muted">
                          No customer-shareable documents available to attach.
                        </p>
                      )}
                    </div>
                  )}
                  {answer.provided_documents && answer.provided_documents.length > 0 && (
                    <div className="providedDocs">
                      <strong>
                        Attached document
                        {answer.provided_documents.length > 1 ? "s" : ""}:
                      </strong>
                      <ul>
                        {answer.provided_documents.map((d) => (
                          <li key={d.document_id}>
                            <a
                              href={api.documentUrl(d.download_url)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {d.title || "Document"}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {answer.remediation_required &&
                    answer.findings &&
                    answer.findings.length > 0 && (
                      <div className="remediation">
                        <strong>Remediation status</strong>
                        <ul>
                          {answer.findings.map((f) => (
                            <li key={f.id}>
                              <span className="findingRef">
                                {f.external_ref || "Finding"}
                              </span>{" "}
                              {f.severity && <span className="sev">{f.severity}</span>}{" "}
                              <span className="findingStatus">
                                {f.status.replace(/_/g, " ")}
                              </span>
                              {(f.status === "open" || f.status === "in_progress") &&
                              f.target_remediation_date
                                ? ` — target ${f.target_remediation_date}`
                                : f.remediated_date
                                  ? ` — remediated ${f.remediated_date}`
                                  : ""}
                              {f.remediation_summary ? (
                                <div className="muted">{f.remediation_summary}</div>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                  <div className="reviewerRow">
                    <label>Reviewer</label>
                    <input
                      value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}
                    />
                  </div>
                  <div className="actions">
                    <button className="btn approve" onClick={() => void act("approve")} disabled={busy}>
                      Approve
                    </button>
                    <button className="btn" onClick={() => void act("edit")} disabled={busy}>
                      Save edit
                    </button>
                    <button className="btn reject" onClick={() => void act("reject")} disabled={busy}>
                      Reject
                    </button>
                    <button className="btn" onClick={() => void act("request_evidence")} disabled={busy}>
                      Request evidence
                    </button>
                    <button className="btn" onClick={() => void act("save_to_library")} disabled={busy}>
                      Save to library
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </main>

        {/* RIGHT — supporting evidence / citations */}
        <aside className="pane evidence">
          <h3>Supporting evidence</h3>
          {!qd ? (
            <p className="muted">—</p>
          ) : qd.citations.length === 0 ? (
            <p className="muted">
              No citations. {answer?.outcome === "needs_input" ? "Flagged as needs-input / needs review." : ""}
            </p>
          ) : (
            qd.citations.map((c) => <CitationCard key={c.chunk_id} c={c} />)
          )}
        </aside>
      </div>
    </div>
  );
}
