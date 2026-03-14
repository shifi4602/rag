"""
workflow.py – Event-Driven RAG Query Workflow
=============================================

Architecture
------------
Each step is an independent unit with a clear typed input and output.
The Workflow dispatcher routes each Event to its registered handler until
a StopEvent signals the end of the pipeline.

Event Flow
----------

  StartEvent (raw question)
       │
       ▼
  validate_input ──[empty / too short / too long]──▶ StopEvent (error)
       │ InputValidatedEvent
       ▼
  retrieve ──────────────[no nodes returned]────────▶ StopEvent (no results)
       │ RetrievedEvent
       ▼
  filter_results
       ├──[≥1 node above cutoff]──▶ FilteredEvent
       └──[all below cutoff]──────▶ FallbackEvent
                                         │
                                    handle_fallback
                                         │ FilteredEvent (used_fallback=True)
                                         ▼
                                     synthesize  ← only step that calls LLM
                                         │ SynthesizedEvent
                                         ▼
                                    format_response
                                         │ StopEvent (answer, sources)
                                         ▼
                                    (answer, sources) returned to caller

Design Decisions
----------------
Q: Does a Step require an LLM call?
   No. Steps 1, 2, 3, 3b, and 5 have zero LLM calls.
   Only Step 4 (synthesize) calls the LLM.

Q: Do we need State management?
   Not for this linear pipeline.  Events carry all necessary data.
   State would be valuable for parallel (fan-out/fan-in) flows or when
   cross-cutting data like conversation history must persist across many steps.

Q: What data belongs in Events vs State?
   Event  → minimal trigger payload: what just happened + inputs for the next step.
   State  → cross-cutting context that many steps need (session ID, user history).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llama_index.core.workflow import (
    Workflow,
    step,
    StartEvent,
    StopEvent,
    Event,
)
from llama_index.utils.workflow import draw_all_possible_flows

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_QUESTION_LENGTH: int = 3
MAX_QUESTION_LENGTH: int = 500

# ── Custom Events ─────────────────────────────────────────────────────────────
# StartEvent and StopEvent are imported from llama_index.core.workflow.
# All custom events extend Event (a Pydantic BaseModel).
# The @step type annotations on each handler are what draw_all_possible_flows
# reads to build the visual graph.


class InputValidatedEvent(Event):
    """Input passed validation; sanitised question ready for retrieval."""
    question: str


class RetrievedEvent(Event):
    """Vector similarity search completed; raw nodes available."""
    question: str
    nodes: Any  # list[NodeWithScore]


class FallbackEvent(Event):
    """All nodes scored below the similarity cutoff; fallback needed."""
    question: str
    nodes: Any


class FilteredEvent(Event):
    """Nodes ready for synthesis (above cutoff or via fallback)."""
    question: str
    nodes: Any
    used_fallback: bool = False


class SynthesizedEvent(Event):
    """LLM produced an answer from the context nodes."""
    answer: str
    nodes: Any


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_sources(nodes: list) -> str:
    """Build a compact, de-duplicated source list from retrieved nodes."""
    seen: set[str] = set()
    lines: list[str] = []

    for node in nodes:
        meta = node.metadata
        tool = meta.get("tool", "Unknown")
        title = meta.get("title") or meta.get("filename", "Unknown")
        key = f"{tool}|{title}"

        if key not in seen:
            seen.add(key)
            score = node.score
            score_str = f" ({score:.2f})" if score is not None else ""
            lines.append(f"• **{tool}** – {title}{score_str}")

    return "\n".join(lines)


# ── Workflow ──────────────────────────────────────────────────────────────────


class RAGWorkflow(Workflow):
    """
    Event-Driven RAG query pipeline built on the LlamaIndex Workflow pattern.

    Each @step is an async handler that consumes one Event type and emits another.
    The LlamaIndex runtime reads the type annotations to route events automatically
    – no manual DISPATCH table needed.

    Usage::

        workflow = RAGWorkflow(retriever, postprocessor, response_synthesizer)
        answer, sources = await workflow.run(question="How do I configure the API?")

    To draw a visual HTML graph of the workflow::

        python workflow.py   →  workflow_graph.html
    """

    def __init__(self, retriever, postprocessor, response_synthesizer, **kwargs):
        super().__init__(**kwargs)
        self._retriever = retriever
        self._postprocessor = postprocessor
        self._response_synthesizer = response_synthesizer

    # ── Steps ─────────────────────────────────────────────────────────────────

    @step
    async def validate_input(self, ev: StartEvent) -> InputValidatedEvent | StopEvent:
        """
        Step 1 – Input Validation
        Sanitises the question and enforces length constraints before
        any expensive API calls are made.
        """
        question = (ev.get("question") or "").strip()

        if not question:
            logger.warning("[validate_input] Empty question")
            return StopEvent(result=("שאלה ריקה. נא להקליד שאלה.", ""))

        if len(question) < MIN_QUESTION_LENGTH:
            logger.warning("[validate_input] Question too short (%d chars)", len(question))
            return StopEvent(result=("השאלה קצרה מדי. נא לפרט יותר.", ""))

        if len(question) > MAX_QUESTION_LENGTH:
            logger.warning("[validate_input] Question too long (%d chars)", len(question))
            return StopEvent(
                result=(f"השאלה ארוכה מדי. נא לקצר ל-{MAX_QUESTION_LENGTH} תווים.", "")
            )

        logger.info("[validate_input] OK → %r", question[:80])
        return InputValidatedEvent(question=question)

    @step
    async def retrieve(self, ev: InputValidatedEvent) -> RetrievedEvent | StopEvent:
        """
        Step 2 – Vector Retrieval
        Queries ChromaDB for the top-K semantically similar nodes.
        """
        nodes = self._retriever.retrieve(ev.question)
        logger.info("[retrieve] %d nodes retrieved", len(nodes))

        if not nodes:
            logger.warning("[retrieve] Vector store returned no results")
            return StopEvent(result=("לא נמצא מידע רלוונטי לשאלתך. נסה לנסח מחדש.", ""))

        return RetrievedEvent(question=ev.question, nodes=nodes)

    @step
    async def filter_results(self, ev: RetrievedEvent) -> FilteredEvent | FallbackEvent:
        """
        Step 3 – Confidence Filtering
        Keeps only nodes above the similarity cutoff.
        Routes to FallbackEvent when confidence is universally low.
        """
        filtered = self._postprocessor.postprocess_nodes(
            ev.nodes, query_str=ev.question
        )
        logger.info(
            "[filter_results] %d / %d nodes above threshold",
            len(filtered), len(ev.nodes),
        )

        if not filtered:
            logger.warning("[filter_results] All below cutoff → FallbackEvent")
            return FallbackEvent(question=ev.question, nodes=ev.nodes)

        return FilteredEvent(question=ev.question, nodes=filtered)

    @step
    async def handle_fallback(self, ev: FallbackEvent) -> FilteredEvent:
        """
        Step 3b – Fallback Strategy
        Uses top-3 raw nodes when all nodes are below the confidence threshold.
        """
        fallback_nodes = ev.nodes[:3]
        logger.info(
            "[handle_fallback] Using top-%d nodes (low-confidence fallback)",
            len(fallback_nodes),
        )
        return FilteredEvent(
            question=ev.question, nodes=fallback_nodes, used_fallback=True
        )

    @step
    async def synthesize(self, ev: FilteredEvent) -> SynthesizedEvent:
        """
        Step 4 – LLM Synthesis   ← the ONLY step that calls the LLM
        Sends filtered context + question to Cohere Command-R+.
        """
        label = " [fallback – low confidence]" if ev.used_fallback else ""
        logger.info("[synthesize] LLM call with %d nodes%s", len(ev.nodes), label)

        response = self._response_synthesizer.synthesize(ev.question, nodes=ev.nodes)
        answer = str(response)

        if ev.used_fallback:
            answer += "\n\n*⚠️ שים לב: התשובה מבוססת על מידע בעל רלוונטיות נמוכה יחסית.*"

        logger.info("[synthesize] Answer ready (%d chars)", len(answer))
        return SynthesizedEvent(answer=answer, nodes=ev.nodes)

    @step
    async def format_response(self, ev: SynthesizedEvent) -> StopEvent:
        """
        Step 5 – Response Formatting
        Assembles the final (answer, sources) tuple for the UI.
        """
        sources = _format_sources(ev.nodes)
        logger.info("[format_response] Pipeline complete")
        return StopEvent(result=(ev.answer, sources))


# ── Visualise the workflow ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s: %(message)s")

    # Pass None components – only the step type-annotations are needed for drawing.
    dummy_wf = RAGWorkflow(retriever=None, postprocessor=None, response_synthesizer=None)

    out = Path(__file__).parent / "workflow_graph.html"
    draw_all_possible_flows(dummy_wf, filename=str(out))
    print(f"Workflow graph saved → {out}")
    print("Open the file in your browser to see the interactive diagram.")
