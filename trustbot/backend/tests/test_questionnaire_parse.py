"""Questionnaire intake parsing — DB-free tests.

Pins the boundary behavior of upload parsing: header detection, CSV + Excel, and the
fail-closed rejections (unsupported type, empty, no question column, oversize).
"""
import io

import openpyxl
import pytest

from app.questionnaires.parse import (
    MAX_QUESTIONS,
    QuestionnaireParseError,
    UnsupportedQuestionnaireError,
    parse_questionnaire,
)

CSV_WITH_HEADERS = (
    b"id,domain,question\n"
    b"Q01,Encryption,Is data encrypted at rest?\n"
    b"Q02,Identity,Is MFA enforced?\n"
)


def test_csv_with_headers_maps_id_domain_question():
    qs = parse_questionnaire(CSV_WITH_HEADERS, filename="q.csv")
    assert [q.text for q in qs] == ["Is data encrypted at rest?", "Is MFA enforced?"]
    assert qs[0].external_id == "Q01"
    assert qs[0].domain == "Encryption"
    assert qs[0].row_index == 0


def test_csv_header_order_independent():
    data = b"question,id\nIs MFA enforced?,Q9\n"
    qs = parse_questionnaire(data, filename="q.csv")
    assert qs[0].text == "Is MFA enforced?"
    assert qs[0].external_id == "Q9"


def test_csv_single_column_headerless():
    data = b"Is data encrypted at rest?\nIs MFA enforced?\n"
    qs = parse_questionnaire(data, filename="q.csv")
    assert [q.text for q in qs] == ["Is data encrypted at rest?", "Is MFA enforced?"]
    assert qs[0].external_id is None


def test_csv_skips_blank_rows():
    data = b"question\nIs data encrypted?\n\n,\nIs MFA enforced?\n"
    qs = parse_questionnaire(data, filename="q.csv")
    assert [q.text for q in qs] == ["Is data encrypted?", "Is MFA enforced?"]


def test_xlsx_round_trip():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["id", "domain", "question"])
    ws.append(["Q1", "Encryption", "Is data encrypted at rest?"])
    ws.append(["Q2", "Compliance", "Do you have a SOC 2 report?"])
    buf = io.BytesIO()
    wb.save(buf)
    qs = parse_questionnaire(buf.getvalue(), filename="q.xlsx")
    assert [q.text for q in qs] == [
        "Is data encrypted at rest?",
        "Do you have a SOC 2 report?",
    ]
    assert qs[1].external_id == "Q2"


def test_rejects_unsupported_type():
    with pytest.raises(UnsupportedQuestionnaireError):
        parse_questionnaire(b"%PDF-1.7 ...", filename="q.pdf")


def test_rejects_empty_file():
    with pytest.raises(QuestionnaireParseError):
        parse_questionnaire(b"", filename="q.csv")


def test_rejects_no_question_column():
    # Multi-column with no recognizable 'question' header → can't guess.
    data = b"foo,bar\n1,2\n3,4\n"
    with pytest.raises(QuestionnaireParseError):
        parse_questionnaire(data, filename="q.csv")


def test_question_text_is_capped():
    long_q = "x" * 9000
    data = b"question\n" + long_q.encode() + b"\n"
    qs = parse_questionnaire(data, filename="q.csv")
    assert len(qs[0].text) <= 4000


def test_too_many_questions_rejected():
    rows = "\n".join(f"q{i}?" for i in range(MAX_QUESTIONS + 5))
    data = b"question\n" + rows.encode()
    with pytest.raises(QuestionnaireParseError):
        parse_questionnaire(data, filename="q.csv")
