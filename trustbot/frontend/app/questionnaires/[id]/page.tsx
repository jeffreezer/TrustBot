"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api";
import type {
  Citation,
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
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    try {
      setDetail(await api.getQuestionnaire(id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load questionnaire");
    }
  }, [id]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const selectQuestion = useCallback(async (questionId: string) => {
    setSelectedId(questionId);
    setQd(null);
    try {
      const data = await api.getQuestion(questionId);
      setQd(data);
      setEditText(data.answer?.answer ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load question");
    }
  }, []);

  const generate = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.generate(id);
      setMessage(`Generated ${r.generated} draft(s), skipped ${r.skipped}.`);
      await loadDetail();
      if (selectedId) await selectQuestion(selectedId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }, [id, loadDetail, selectQuestion, selectedId]);

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

  const answer = qd?.answer ?? null;
  const undrafted = detail?.questions.filter((q) => q.status === "undrafted").length ?? 0;

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
          <button className="btn primary" onClick={generate} disabled={busy}>
            {busy ? "Working…" : undrafted > 0 ? `Generate ${undrafted} draft(s)` : "Regenerate"}
          </button>
          <a className="btn" href={api.exportUrl(id, "csv")}>
            Export CSV
          </a>
          <a className="btn" href={api.exportUrl(id, "xlsx")}>
            Export Excel
          </a>
        </div>
      </header>

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

                  {answer.needs_human_review && (
                    <div className="reviewBanner">
                      <strong>Needs human review.</strong>{" "}
                      {answer.review_reason || "The system could not fully support this answer."}
                    </div>
                  )}

                  <label className="fieldLabel">Draft answer (editable)</label>
                  <textarea
                    className="answerBox"
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    rows={10}
                  />
                  {answer.exceptions && (
                    <p className="exceptions">
                      <strong>Exception:</strong> {answer.exceptions}
                    </p>
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
              No citations. {answer?.outcome === "unknown" ? "Flagged as unknown / needs review." : ""}
            </p>
          ) : (
            qd.citations.map((c) => <CitationCard key={c.chunk_id} c={c} />)
          )}
        </aside>
      </div>
    </div>
  );
}
