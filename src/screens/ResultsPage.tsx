import React, { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useRecoilValue } from "recoil";
import { submissionsState } from "../state/submissions";
import type { Submission } from "../state/submissions";

const PAGE_SIZE = 50;

function fmt(ts: string) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function resultFor(s: Submission) {
  return s.mode === "SINGLE" ? s.result : s.overallResult;
}

function pillClass(result: string) {
  if (result === "HIT") return "resultPillHit";
  if (result === "NO_HIT") return "resultPillNoHit";
  return "resultPillError";
}

export function ResultsPage() {
  const submissions = useRecoilValue(submissionsState);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(submissions.length / PAGE_SIZE));
  const [page, setPage] = useState(1);

  // Batch expand
  const [openBatchId, setOpenBatchId] = useState<string | null>(null);

  // Details modal
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTitle, setDetailTitle] = useState("");
  const [detailJson, setDetailJson] = useState<any>(null);

  // Keep page in range if submissions length changes
  useMemo(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const pageItems = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return submissions.slice(start, start + PAGE_SIZE);
  }, [submissions, page]);

  function openDetails(title: string, json: any) {
    setDetailTitle(title);
    setDetailJson(json ?? null);
    setDetailOpen(true);
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div>
          <h2>Screening Results</h2>
          <p>
            Showing <b>{PAGE_SIZE}</b> per page • Total <b>{submissions.length}</b>
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Link to="/" className="pill">
            Back to Screening
          </Link>
        </div>
      </div>

      <div className="panelBody">
        {submissions.length === 0 && (
          <div className="alert" style={{ color: "var(--muted)" }}>
            No submissions yet.
          </div>
        )}

        {submissions.length > 0 && (
          <>
            {/* Pagination controls (top) */}
            <div className="pager">
              <button
                className="btnGhost"
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                Prev
              </button>

              <div className="pagerInfo">
                Page <b>{page}</b> of <b>{totalPages}</b>
              </div>

              <button
                className="btnGhost"
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
              >
                Next
              </button>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table className="resultsTable">
                <thead>
                  <tr>
                    <th align="left">Date</th>
                    <th align="left">Mode</th>
                    <th align="left">Name / File</th>
                    <th align="left">Type</th>
                    <th align="left">Result</th>
                    <th align="right">Action</th>
                  </tr>
                </thead>

                <tbody>
                  {pageItems.map((s) => {
                    const r = resultFor(s);
                    const isBatchOpen = s.mode === "BATCH" && openBatchId === s.id;

                    return (
                      <React.Fragment key={s.id}>
                        <tr className="resultsRow">
                          <td className="td">{fmt(s.createdAt)}</td>
                          <td className="td">{s.mode}</td>
                          <td className="td">{s.mode === "SINGLE" ? s.displayName : s.fileName}</td>
                          <td className="td">{s.mode === "SINGLE" ? s.customerType : "—"}</td>

                          {/* Result + details link */}
                          <td className="td">
                            <div className="resultCell">
                              <span className={`pill ${pillClass(r)}`}>{r}</span>

                              {/* Show details link under result */}
                              {s.mode === "SINGLE" && s.result === "HIT" && s.details ? (
                                <button
                                  type="button"
                                  className="linkBtn"
                                  onClick={() => openDetails(`Hit details: ${s.displayName}`, s.details)}
                                >
                                  View details
                                </button>
                              ) : null}

                              {s.mode === "BATCH" && s.overallResult === "HIT" ? (
                                <span className="hintSmall">Open batch to view hit item details</span>
                              ) : null}
                            </div>
                          </td>

                          <td className="td" style={{ textAlign: "right" }}>
                            {s.mode === "BATCH" ? (
                              <button
                                className="btnGhost"
                                type="button"
                                onClick={() => setOpenBatchId(isBatchOpen ? null : s.id)}
                              >
                                {isBatchOpen ? "Hide" : "View"}
                              </button>
                            ) : (
                              <span className="hintSmall">—</span>
                            )}
                          </td>
                        </tr>

                        {/* Batch expand */}
                        {s.mode === "BATCH" && isBatchOpen && (
                          <tr>
                            <td colSpan={6} style={{ padding: "0 0 14px 0" }}>
                              <div className="batchBox">
                                <div className="batchHeader">
                                  <b>Batch Items</b>
                                  <span className="hintSmall">
                                    Total: <b>{s.items.length}</b>
                                  </span>
                                </div>

                                <div className="batchList">
                                  {s.items.map((it, idx) => (
                                    <div key={idx} className="batchLine">
                                      <div className="batchLeft">
                                        <span className="batchName">{it.displayName}</span>
                                        <span className="hintSmall">{it.customerType}</span>
                                      </div>

                                      <div className="batchRight">
                                        <span className={`pill ${pillClass(it.result)}`}>{it.result}</span>

                                        {it.result === "HIT" && it.details ? (
                                          <button
                                            type="button"
                                            className="linkBtn"
                                            onClick={() => openDetails(`Hit details: ${it.displayName}`, it.details)}
                                          >
                                            View details
                                          </button>
                                        ) : null}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination controls (bottom) */}
            <div className="pager" style={{ marginTop: 12 }}>
              <button
                className="btnGhost"
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                Prev
              </button>

              <div className="pagerInfo">
                Page <b>{page}</b> of <b>{totalPages}</b>
              </div>

              <button
                className="btnGhost"
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>

      {/* Details Modal */}
      {detailOpen && (
        <div className="modalBackdrop" onMouseDown={() => setDetailOpen(false)}>
          <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h3 style={{ margin: 0 }}>{detailTitle}</h3>
                <div className="hintSmall">OpenSanctions match response</div>
              </div>
              <button className="btnGhost" type="button" onClick={() => setDetailOpen(false)}>
                Close
              </button>
            </div>

            <pre className="jsonBox">{JSON.stringify(detailJson, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
