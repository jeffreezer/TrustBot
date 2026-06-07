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
from dataclasses import dataclass, field


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


# --- Adaptive retrieval loop (Phase 6) -------------------------------------
# Provider-neutral tool-calling types. The loop control + tool execution live in the
# answer path (server-side, org-scoped, audited); a provider only translates these to/from
# its native tool API. Tool RESULTS are untrusted data fed back as tool-result messages —
# never system instructions (06 §7).


@dataclass(frozen=True)
class ToolSpec:
    """A read-only tool offered to the agent (name + JSON-schema for its arguments)."""

    name: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolCall:
    """A model-requested tool invocation. ``arguments`` never includes org_id — the server
    enforces tenancy from the request context."""

    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResultMsg:
    """The server's reply to one tool call, fed back to the model as data."""

    call_id: str
    name: str
    content: str  # JSON string the model sees


@dataclass(frozen=True)
class AssistantTurn:
    """One model turn: retrieval tool call(s), OR the final structured draft (the model
    emitted ``emit_answer_draft``). ``text`` preserves any prose for transcript fidelity."""

    tool_calls: tuple[ToolCall, ...] = ()
    draft_json: str | None = None
    text: str = ""


@dataclass(frozen=True)
class AgentRound:
    """A completed loop round: the model's turn + the tool results returned to it."""

    assistant: AssistantTurn
    results: tuple[ToolResultMsg, ...] = field(default_factory=tuple)


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

    # --- Adaptive retrieval loop (Phase 6); optional per provider -----------

    def supports_tools(self) -> bool:
        """Whether this provider can run the tool-calling loop. Providers that can't fall
        back to the one-shot ``draft`` path (the loop is an upgrade, never a requirement)."""
        return False

    def agent_turn(
        self,
        *,
        system: str,
        question: str,
        history: tuple[AgentRound, ...],
        tools: tuple[ToolSpec, ...],
        force_final: bool,
    ) -> AssistantTurn:
        """One turn of the adaptive loop: given the system prompt (trusted), the question,
        and the prior rounds (assistant tool calls + their results, as DATA), return either
        retrieval tool calls or the final ``emit_answer_draft`` (in ``draft_json``).

        ``force_final=True`` requires the provider to emit the draft now (final budgeted
        turn). Implementations MUST keep ``system`` trusted and everything in ``history``
        as data — tool results never alter the instructions.
        """
        raise NotImplementedError(f"{self.name} does not support the tool-calling loop")
