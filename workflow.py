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

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

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

# ── Routing prompt ────────────────────────────────────────────────────────────

ROUTING_PROMPT = """\
You are a query router for a RAG documentation system.
Decide which retrieval strategy is best for the user's question.

Choose "semantic" when the question asks for explanations, how-to guides,
architecture details, configuration steps, or any open-ended conceptual question.

Choose "structured" when the question:
- Asks to LIST or ENUMERATE **all** items of a category
  (e.g. "all decisions", "all rules", "all warnings", "all dependencies")
- Asks for the **latest / current / most-recent** guideline or rule on a topic
- Filters by **time** (last week, recently, last N days)
- Asks for a **complete inventory** of something across the whole project

If "structured", also specify:
- "query_type": one of
    "all_type"    → return every item of a given category
    "recent"      → items from the last N days
    "tags"        → items matching given tags / keywords
    "text_search" → keyword search inside the structured data
- "item_type": "decisions" | "rules" | "warnings" | "dependencies" | "changes" | null
- "tags": list of relevant keyword strings (can be [])
- "days": integer (for "recent") or null
- "search_text": a keyword or short phrase (or null)

Return ONLY valid JSON — no explanation, no markdown.
Examples:
  {{"route": "semantic"}}
  {{"route": "structured", "query_type": "all_type", "item_type": "decisions", "tags": [], "days": null, "search_text": null}}
  {{"route": "structured", "query_type": "recent", "item_type": null, "tags": [], "days": 7, "search_text": null}}
  {{"route": "structured", "query_type": "text_search", "item_type": "rules", "tags": [], "days": null, "search_text": "RTL"}}

User question: {question}
"""

# ── Structured synthesis prompt ───────────────────────────────────────────────

STRUCTURED_SYNTHESIS_PROMPT = """\
You are a documentation assistant. The user asked:
"{question}"

Here are the relevant items retrieved from the project's structured knowledge base:
{items_json}

Provide a clear, well-structured answer based on this data.
If the list is long, use bullet points or numbered lists for readability.
If no items were found, say so politely and suggest rephrasing.
Answer in the same language as the question.
"""

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


class SemanticRouteEvent(Event):
    """Router chose the semantic (vector) retrieval path."""
    question: str


class StructuredRouteEvent(Event):
    """Router chose the structured JSON store path."""
    question: str
    query_type: str          # "all_type" | "recent" | "tags" | "text_search"
    item_type: Optional[str] = None
    tags: list = []
    days: Optional[int] = None
    search_text: Optional[str] = None


class StructuredResultsEvent(Event):
    """Structured store returned results; ready for LLM synthesis."""
    question: str
    items: list              # list of plain dicts from StructuredStore
    query_description: str


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


def _format_structured_sources(items: list) -> str:
    """Build a compact, de-duplicated source list from structured store items."""
    seen: set[str] = set()
    lines: list[str] = []

    for item in items:
        src = item.get("source", {})
        tool = src.get("tool", "unknown").replace("_", " ").title()
        file_path = src.get("file", "")
        filename = Path(file_path).name if file_path else "Unknown"
        key = f"{tool}|{filename}"
        if key not in seen:
            seen.add(key)
            lines.append(f"• **{tool}** – {filename}")

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

    def __init__(
        self,
        retriever,
        postprocessor,
        response_synthesizer,
        llm=None,
        structured_store=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._retriever = retriever
        self._postprocessor = postprocessor
        self._response_synthesizer = response_synthesizer
        self._llm = llm
        self._structured_store = structured_store

    # ── Steps ─────────────────────────────────────────────────────────────────

    @step
    async def validate_input(self, ev: StartEvent) -> InputValidatedEvent | StopEvent:  # noqa: E501
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
    async def route_query(
        self, ev: InputValidatedEvent
    ) -> SemanticRouteEvent | StructuredRouteEvent:
        """
        Step 1b – Query Routing  ← LLM call (Router)
        Uses the LLM to classify the question and choose between:
          • semantic path  → vector similarity search in ChromaDB
          • structured path → typed query against the extracted JSON store

        Falls back to semantic search if the structured store is unavailable
        or if the LLM response cannot be parsed.
        """
        # Default to semantic if the store is not ready
        if self._structured_store is None or not self._structured_store.is_available:
            logger.info("[route_query] Structured store unavailable → semantic")
            return SemanticRouteEvent(question=ev.question)

        prompt = ROUTING_PROMPT.format(question=ev.question)
        try:
            response = await self._llm.acomplete(prompt)
            raw = str(response).strip()

            # Strip markdown fences if present
            fence = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
            if fence:
                raw = fence.group(1).strip()

            routing = json.loads(raw)
        except Exception as exc:
            logger.warning(
                "[route_query] Routing parse error (%s) → fallback to semantic", exc
            )
            return SemanticRouteEvent(question=ev.question)

        route = routing.get("route", "semantic")
        logger.info("[route_query] Route decided: %s", route)

        if route == "structured":
            return StructuredRouteEvent(
                question=ev.question,
                query_type=routing.get("query_type", "text_search"),
                item_type=routing.get("item_type"),
                tags=routing.get("tags") or [],
                days=routing.get("days"),
                search_text=routing.get("search_text"),
            )

        return SemanticRouteEvent(question=ev.question)

    @step
    async def retrieve(self, ev: SemanticRouteEvent) -> RetrievedEvent | StopEvent:
        """
        Step 2 – Vector Retrieval  (semantic path)
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
        Step 5 – Response Formatting  (semantic path)
        Assembles the final (answer, sources) tuple for the UI.
        """
        sources = _format_sources(ev.nodes)
        logger.info("[format_response] Pipeline complete")
        return StopEvent(result=(ev.answer, sources))

    # ── Structured path ───────────────────────────────────────────────────────

    @step
    async def execute_structured(
        self, ev: StructuredRouteEvent
    ) -> StructuredResultsEvent | StopEvent:
        """
        Step 2s – Structured Store Query  (structured path)
        Translates the routing parameters into a StructuredStore call
        and returns the matching items.
        """
        store = self._structured_store
        qt = ev.query_type

        if qt == "all_type" and ev.item_type:
            items = store.get_all(ev.item_type)
            desc = f"כל הפריטים מסוג '{ev.item_type}'"

        elif qt == "recent":
            days = ev.days or 7
            items = store.get_recent(days=days)
            desc = f"פריטים מ-{days} הימים האחרונים"

        elif qt == "tags" and ev.tags:
            items = store.get_by_tags(ev.tags)
            desc = f"פריטים עם תגיות: {', '.join(ev.tags)}"

        elif qt == "text_search" and ev.search_text:
            items = store.search_text(ev.search_text, item_type=ev.item_type)
            desc = f"חיפוש טקסט: '{ev.search_text}'"

        else:
            # Generic fallback: return all items of the requested type,
            # or the entire store if no type was specified
            if ev.item_type:
                items = store.get_all(ev.item_type)
                desc = f"כל הפריטים מסוג '{ev.item_type}'"
            else:
                items = store.get_all_items()
                desc = "כל הפריטים במאגר"

        logger.info(
            "[execute_structured] query_type=%s → %d items", qt, len(items)
        )

        if not items:
            return StopEvent(
                result=(
                    f"לא נמצאו פריטים מתאימים עבור: {desc}. "
                    "ניתן להריץ את extract.py כדי לעדכן את מאגר הנתונים המובנה.",
                    "",
                )
            )

        return StructuredResultsEvent(
            question=ev.question,
            items=items,
            query_description=desc,
        )

    @step
    async def synthesize_structured(
        self, ev: StructuredResultsEvent
    ) -> StopEvent:
        """
        Step 3s – LLM Synthesis  (structured path)
        Sends the structured items as context to the LLM for a final answer.
        """
        items_json = json.dumps(ev.items, ensure_ascii=False, indent=2)
        prompt = STRUCTURED_SYNTHESIS_PROMPT.format(
            question=ev.question,
            items_json=items_json,
        )
        logger.info(
            "[synthesize_structured] LLM call with %d items", len(ev.items)
        )
        response = await self._llm.acomplete(prompt)
        answer = str(response).strip()

        sources = _format_structured_sources(ev.items)
        logger.info("[synthesize_structured] Answer ready (%d chars)", len(answer))
        return StopEvent(result=(answer, sources))


# ── Visualise the workflow ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s: %(message)s")

    # Pass None components – only the step type-annotations are needed for drawing.
    dummy_wf = RAGWorkflow(
        retriever=None,
        postprocessor=None,
        response_synthesizer=None,
        llm=None,
        structured_store=None,
    )

    out = Path(__file__).parent / "workflow_graph.html"
    draw_all_possible_flows(dummy_wf, filename=str(out))
    print(f"Workflow graph saved → {out}")
    print("Open the file in your browser to see the interactive diagram.")
