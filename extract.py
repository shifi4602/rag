"""
extract.py – Structured Data Extraction Pipeline
=================================================

Reads every .md file under sample_project/, sends each file to the Cohere LLM
with an extraction prompt, and writes the combined result to extracted_data.json.

Extracted item types
--------------------
  decisions    – technical / architectural decisions made in the project
  rules        – guidelines and constraints that must be followed
  warnings     – sensitive areas, "do not touch" notes, high-risk operations
  dependencies – external libraries, services, or APIs the project relies on
  changes      – recent updates, migrations, or notable refactors

Event Flow
----------

  StartEvent (source_dir)
        │
        ▼
  discover_files ──[dir missing / no .md]──► StopEvent (error)
        │ FilesDiscoveredEvent
        ▼
  extract_files   ← calls LLM once per file
        │ AllExtractedEvent
        ▼
  assemble_store  ← builds the full JSON and writes it to disk
        │ StopEvent (store dict)

Run:
  python extract.py
  python extract.py --draw   →  extract_graph.html
"""

# SSL fix for Windows / Python 3.14: inject system certificate store
import truststore
truststore.inject_into_ssl()

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from llama_index.core import Settings
from llama_index.core.workflow import Event, StartEvent, StopEvent, Workflow, step
from llama_index.llms.cohere import Cohere
from llama_index.utils.workflow import draw_all_possible_flows

from config import (
    COHERE_API_KEY,
    COHERE_LLM_MODEL,
    EXTRACTED_DATA_PATH,
    SAMPLE_PROJECT_DIR,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Schema version ────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"

# ── Stable ID generation ──────────────────────────────────────────────────────

_COUNTERS: dict[str, int] = {}


def _next_id(prefix: str) -> str:
    _COUNTERS[prefix] = _COUNTERS.get(prefix, 0) + 1
    return f"{prefix}-{_COUNTERS[prefix]:03d}"


# ── Path helpers ──────────────────────────────────────────────────────────────

def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return "sha256:" + h.hexdigest()[:16]


def _tool_from_path(path: Path) -> str:
    parts = str(path).replace("\\", "/").lower()
    if "/cursor/" in parts:
        return "cursor"
    if "/claude" in parts:
        return "claude_code"
    return "unknown"


# ── LLM extraction prompt ─────────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are a structured data extractor for project documentation.
Analyse the markdown file below and extract ALL items in these five categories:

1. decisions   – Technical/architectural decisions (e.g. "chose PostgreSQL", "API versioning via URL prefix")
2. rules       – Guidelines or constraints that MUST be followed (e.g. "all Hebrew UIs must use RTL", "API routes must be versioned")
3. warnings    – Sensitive areas, "do not touch" notes, or dangerous operations
4. dependencies – External libraries, services, APIs, or tools the project depends on
5. changes     – Recent updates, migrations, refactors, or notable additions mentioned in the file

Return ONLY a valid JSON object — no markdown fences, no commentary — with this exact structure:
{{
  "decisions": [
    {{"title": "<short title>", "summary": "<one-sentence explanation>", "tags": ["<tag>"]}}
  ],
  "rules": [
    {{"rule": "<the rule statement>", "scope": "<ui|api|db|auth|testing|general>", "notes": "<optional exception or clarification>"}}
  ],
  "warnings": [
    {{"area": "<component or area>", "message": "<what to be careful about>", "severity": "high|medium|low"}}
  ],
  "dependencies": [
    {{"name": "<package or service>", "purpose": "<what it is used for>", "version": "<version string or null>"}}
  ],
  "changes": [
    {{"description": "<what changed>", "impact": "<what it affects>", "date_hint": "<date/version hint or null>"}}
  ]
}}

Use an empty array [] for any category that has no items.

File path: {filepath}
File content:
---
{content}
---"""


# ── Events ────────────────────────────────────────────────────────────────────

class FilesDiscoveredEvent(Event):
    """All eligible .md files found under source_dir."""
    files: list  # list[Path]


class AllExtractedEvent(Event):
    """Per-file extraction results ready for assembly."""
    file_results: list  # list[dict]


# ── Workflow ──────────────────────────────────────────────────────────────────

class ExtractionWorkflow(Workflow):
    """
    Event-Driven structured data extraction pipeline.

    Each @step consumes one Event type and emits the next.

    Usage::

        llm = Cohere(api_key=..., model=...)
        store = await ExtractionWorkflow(llm=llm, timeout=600).run(
            source_dir=SAMPLE_PROJECT_DIR
        )
    """

    def __init__(self, llm, **kwargs):
        super().__init__(**kwargs)
        self._llm = llm

    # ── Step 1 ────────────────────────────────────────────────────────────────

    @step
    async def discover_files(self, ev: StartEvent) -> FilesDiscoveredEvent | StopEvent:
        """Locate all .md files under source_dir."""
        source_dir = Path(ev.get("source_dir"))

        if not source_dir.exists():
            logger.error("[discover_files] Not found: %s", source_dir)
            return StopEvent(result={"error": f"Directory not found: {source_dir}"})

        files = sorted(source_dir.rglob("*.md"))
        if not files:
            logger.error("[discover_files] No .md files in: %s", source_dir)
            return StopEvent(result={"error": f"No .md files found in {source_dir}"})

        logger.info("[discover_files] %d .md files found", len(files))
        for f in files:
            logger.info("    • %s", f.relative_to(source_dir))
        return FilesDiscoveredEvent(files=files)

    # ── Step 2 ────────────────────────────────────────────────────────────────

    @step
    async def extract_files(self, ev: FilesDiscoveredEvent) -> AllExtractedEvent:
        """Call the LLM once per file to extract structured items."""
        results = []

        for file_path in ev.files:
            logger.info("[extract_files] → %s", file_path.name)

            content = file_path.read_text(encoding="utf-8", errors="replace")
            prompt = EXTRACTION_PROMPT.format(
                filepath=str(file_path).replace("\\", "/"),
                content=content[:8000],  # guard against token limits
            )

            try:
                response = await self._llm.acomplete(prompt)
                raw_text = str(response).strip()

                # Strip potential markdown code fences the LLM might add
                fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw_text)
                if fence_match:
                    raw_text = fence_match.group(1).strip()

                raw_items = json.loads(raw_text)
            except Exception as exc:
                logger.warning(
                    "[extract_files] Parse error for %s: %s – using empty item set",
                    file_path.name, exc,
                )
                raw_items = {
                    "decisions": [], "rules": [], "warnings": [],
                    "dependencies": [], "changes": [],
                }

            stat = file_path.stat()
            results.append({
                "file": file_path,
                "tool": _tool_from_path(file_path),
                "last_modified": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "file_hash": _file_hash(file_path),
                "raw_items": raw_items,
            })

        return AllExtractedEvent(file_results=results)

    # ── Step 3 ────────────────────────────────────────────────────────────────

    @step
    async def assemble_store(self, ev: AllExtractedEvent) -> StopEvent:
        """Assemble all extracted items into the JSON store and write to disk."""
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        store: dict = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso,
            "sources": [],
            "items": {
                "decisions": [],
                "rules": [],
                "warnings": [],
                "dependencies": [],
                "changes": [],
            },
        }

        for result in ev.file_results:
            file_path: Path = result["file"]
            file_uri = str(file_path).replace("\\", "/")

            store["sources"].append({
                "tool": result["tool"],
                "file": file_uri,
                "last_modified": result["last_modified"],
                "hash": result["file_hash"],
            })

            source_meta = {
                "tool": result["tool"],
                "file": file_uri,
                "observed_at": result["last_modified"],
            }

            raw = result["raw_items"]

            for item in raw.get("decisions", []):
                store["items"]["decisions"].append({
                    "id": _next_id("dec"),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "tags": item.get("tags", []),
                    "source": source_meta,
                    "observed_at": result["last_modified"],
                })

            for item in raw.get("rules", []):
                store["items"]["rules"].append({
                    "id": _next_id("rule"),
                    "rule": item.get("rule", ""),
                    "scope": item.get("scope", ""),
                    "notes": item.get("notes", ""),
                    "source": source_meta,
                    "observed_at": result["last_modified"],
                })

            for item in raw.get("warnings", []):
                store["items"]["warnings"].append({
                    "id": _next_id("warn"),
                    "area": item.get("area", ""),
                    "message": item.get("message", ""),
                    "severity": item.get("severity", "medium"),
                    "source": source_meta,
                    "observed_at": result["last_modified"],
                })

            for item in raw.get("dependencies", []):
                store["items"]["dependencies"].append({
                    "id": _next_id("dep"),
                    "name": item.get("name", ""),
                    "purpose": item.get("purpose", ""),
                    "version": item.get("version"),
                    "source": source_meta,
                    "observed_at": result["last_modified"],
                })

            for item in raw.get("changes", []):
                store["items"]["changes"].append({
                    "id": _next_id("chg"),
                    "description": item.get("description", ""),
                    "impact": item.get("impact", ""),
                    "date_hint": item.get("date_hint"),
                    "source": source_meta,
                    "observed_at": result["last_modified"],
                })

        EXTRACTED_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXTRACTED_DATA_PATH.write_text(
            json.dumps(store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        counts = {k: len(v) for k, v in store["items"].items()}
        total = sum(counts.values())
        logger.info(
            "[assemble_store] %d total items %s → %s",
            total, counts, EXTRACTED_DATA_PATH,
        )
        return StopEvent(result=store)


# ── Entry point ───────────────────────────────────────────────────────────────

async def _run():
    llm = Cohere(api_key=COHERE_API_KEY, model=COHERE_LLM_MODEL)
    Settings.llm = llm

    wf = ExtractionWorkflow(llm=llm, timeout=600)
    store = await wf.run(source_dir=SAMPLE_PROJECT_DIR)

    if "error" in store:
        logger.error("Extraction failed: %s", store["error"])
        return

    counts = {k: len(v) for k, v in store["items"].items()}
    logger.info("Extraction complete! %s", counts)


def main():
    logger.info("Structured Data Extraction – START")
    asyncio.run(_run())


if __name__ == "__main__":
    import sys
    if "--draw" in sys.argv:
        out = Path(__file__).parent / "extract_graph.html"
        llm = Cohere(api_key=COHERE_API_KEY, model=COHERE_LLM_MODEL)
        draw_all_possible_flows(ExtractionWorkflow(llm=llm), filename=str(out))
        print(f"Extract graph saved → {out}")
    else:
        main()
