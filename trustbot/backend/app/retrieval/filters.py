"""Retrieval filters — the tenancy and shareability gate on every search.

``org_id`` is required and applied to every query (CLAUDE.md: "enforce org_id
scoping on every query"). The optional filters let a caller (and Phase 4 answer
generation) constrain by source type, confidentiality, and customer-shareability so
internal-only material never reaches a customer-facing answer.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalFilters:
    org_id: uuid.UUID
    source_types: Sequence[str] | None = None
    confidentiality: Sequence[str] | None = None
    # When True, only chunks explicitly flagged customer_shareable in their meta are
    # returned — the filter Phase 4 uses for external answers.
    customer_shareable: bool | None = None
