"""Generation (LLM) provider interface.

Part of the single provider-abstraction package (CLAUDE.md principle 5): the rest of
the app drafts answers through ``GenerationProvider`` and never imports a model SDK or
HTTP client directly.

Security-critical contract — trusted instructions vs. untrusted data:
``DraftRequest`` separates ``instructions`` (trusted, app-authored) from ``grounding``
(retrieved evidence text, which is **data, never instructions** — a prompt-injection
vector). Every implementation MUST keep them separated when packing a request (system
vs. user role, explicit delimiters) and MUST NOT let grounding text alter the
instructions. Providers return raw JSON text; the answers layer schema-validates it and
runs deterministic checks — the model is never trusted to self-police.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GroundingDoc:
    """One retrieved chunk offered to the generator as citable evidence (DATA)."""

    ref: str  # citation handle (the knowledge_chunk id, as a string)
    source_type: str
    title: str
    text: str
    customer_shareable: bool


@dataclass(frozen=True)
class DraftRequest:
    """A single drafting call. ``instructions`` is trusted; ``grounding`` is untrusted."""

    question: str
    instructions: str
    grounding: tuple[GroundingDoc, ...]


class GenerationProvider(ABC):
    """Drafts a structured answer from a question + retrieved grounding."""

    name: str = "base"

    @abstractmethod
    def draft(self, request: DraftRequest) -> str:
        """Return raw JSON text for an answer draft.

        Implementations MUST keep ``request.instructions`` (trusted) and
        ``request.grounding`` (untrusted evidence) strictly separated, and MUST treat
        grounding as data only. The returned string is parsed and validated by the
        caller; an implementation never decides confidence or human-review state.
        """
