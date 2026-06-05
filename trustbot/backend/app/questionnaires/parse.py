"""Parse an uploaded questionnaire (CSV / Excel) into a list of questions.

Security: the file is **data, never instructions** (CLAUDE.md). This module only
decodes and reads tabular cells — it never evaluates formulas, follows links, or
executes anything. Type and size are validated at the route boundary before this runs;
here we reject anything that isn't CSV/Excel and bound the row count and text length.
PDF intake is not built yet (it would need a new parser dependency) — it's rejected
explicitly rather than mishandled.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

MAX_QUESTIONS = 2000
MAX_QUESTION_CHARS = 4000

_CSV_SUFFIXES = {".csv", ".tsv"}
_EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}

# Column-header synonyms (normalized: lowercased, collapsed whitespace).
_QUESTION_HEADERS = {
    "question", "questions", "question text", "text", "query", "item", "control question",
    "requirement",
}
_ID_HEADERS = {"id", "question id", "qid", "#", "no", "no.", "number", "ref", "item id"}
_DOMAIN_HEADERS = {"domain", "category", "section", "topic", "area", "control domain"}


class QuestionnaireParseError(Exception):
    """The file is a supported type but couldn't be parsed into questions."""


class UnsupportedQuestionnaireError(QuestionnaireParseError):
    """The file type isn't handled by questionnaire intake (e.g. PDF/binary)."""


@dataclass(frozen=True)
class ParsedQuestion:
    text: str
    external_id: str | None
    domain: str | None
    row_index: int


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _decode_csv(data: bytes, *, delimiter: str) -> list[list[str]]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 decodes any byte string
        text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[_norm(c) for c in row] for row in reader]


def _read_xlsx(data: bytes) -> list[list[str]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        best: list[list[str]] = []
        for ws in wb.worksheets:
            rows = [[_norm(c) for c in row] for row in ws.iter_rows(values_only=True)]
            # Prefer a sheet that has a recognizable question header.
            if any(_find_header(rows[i]) is not None for i in range(min(len(rows), 10))):
                return rows
            if len(rows) > len(best):
                best = rows
        return best
    finally:
        wb.close()


def _find_header(row: list[str]) -> int | None:
    """Index of the question column in ``row``, or None if this isn't a header row."""
    for i, cell in enumerate(row):
        if cell.lower() in _QUESTION_HEADERS:
            return i
    return None


def _col(row: list[str], headers: set[str]) -> int | None:
    for i, cell in enumerate(row):
        if cell.lower() in headers:
            return i
    return None


def _rows_to_questions(rows: list[list[str]]) -> list[ParsedQuestion]:
    rows = [r for r in rows if any(c for c in r)]  # drop fully-blank rows
    if not rows:
        raise QuestionnaireParseError("the questionnaire is empty")

    header_idx = next(
        (i for i, r in enumerate(rows) if _find_header(r) is not None), None
    )
    if header_idx is not None:
        header = rows[header_idx]
        q_col = _find_header(header)
        id_col = _col(header, _ID_HEADERS)
        domain_col = _col(header, _DOMAIN_HEADERS)
        body = rows[header_idx + 1 :]
        get = lambda r, i: r[i] if i is not None and i < len(r) else ""  # noqa: E731
    elif all(len(r) == 1 for r in rows):
        # Headerless single-column list of questions.
        q_col, id_col, domain_col = 0, None, None
        body = rows
        get = lambda r, i: r[i] if i is not None and i < len(r) else ""  # noqa: E731
    else:
        raise QuestionnaireParseError(
            "could not find a 'question' column; include a header row with a "
            "'question' column, or a single-column list of questions"
        )

    questions: list[ParsedQuestion] = []
    for offset, row in enumerate(body):
        text = get(row, q_col)
        if not text:
            continue
        questions.append(
            ParsedQuestion(
                text=text[:MAX_QUESTION_CHARS],
                external_id=(get(row, id_col) or None),
                domain=(get(row, domain_col) or None),
                row_index=offset,
            )
        )
        if len(questions) > MAX_QUESTIONS:
            raise QuestionnaireParseError(
                f"questionnaire exceeds the {MAX_QUESTIONS}-question limit"
            )

    if not questions:
        raise QuestionnaireParseError("no questions found in the file")
    return questions


def parse_questionnaire(
    data: bytes, *, filename: str, content_type: str | None = None
) -> list[ParsedQuestion]:
    """Parse CSV/Excel bytes into questions. Raises for unsupported/empty files."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in _CSV_SUFFIXES:
        rows = _decode_csv(data, delimiter="\t" if suffix == ".tsv" else ",")
    elif suffix in _EXCEL_SUFFIXES:
        rows = _read_xlsx(data)
    else:
        raise UnsupportedQuestionnaireError(
            f"unsupported questionnaire type {suffix!r}; upload CSV or Excel "
            "(PDF intake is not supported yet)"
        )
    return _rows_to_questions(rows)
