# 🧠 RAG – Agentic Coding Docs System

> A production-ready **Retrieval-Augmented Generation (RAG)** system that lets you chat with your project documentation, powered by **Cohere**, **ChromaDB**, and **LlamaIndex Workflows**.

---

## 📋 Table of Contents

1. [What Does This Project Do?](#-what-does-this-project-do)
2. [Quick Start](#-quick-start)
3. [Project Structure](#-project-structure)
4. [Architecture Overview](#-architecture-overview)
5. [Module Deep-Dive](#-module-deep-dive)
   - [config.py](#-configpy--configuration-hub)
   - [ingest.py](#-ingestpy--ingestion-pipeline)
   - [extract.py](#-extractpy--structured-data-extractor)
   - [structured_store.py](#-structured_storepy--query-layer)
   - [workflow.py](#-workflowpy--rag-query-pipeline)
   - [app.py](#-apppy--gradio-chat-ui)
6. [The Dual-Path Routing System](#-the-dual-path-routing-system)
7. [Example Questions & What Happens](#-example-questions--what-happens)
8. [The Sample Project](#-the-sample-project)
9. [Data Flows – Step by Step](#-data-flows--step-by-step)
10. [Configuration Reference](#-configuration-reference)
11. [Dependencies](#-dependencies)

---

## 🤔 What Does This Project Do?

This project builds a **question-answering chatbot over your markdown documentation**. You point it at a folder of `.md` files (the `sample_project/` directory), and then you can ask natural-language questions about the content.

The system is smart enough to choose **how** to answer each question:

| Question Type | Example | Strategy Used |
|---|---|---|
| Conceptual / How-to | "How do I configure the API?" | 🔵 Semantic search (ChromaDB) |
| List all items | "List all the technical decisions" | 🟠 Structured JSON query |
| Recent changes | "What changed in the last 7 days?" | 🟠 Structured JSON query |
| Text search | "Find all rules about RTL" | 🟠 Structured JSON query |

The UI is a **Gradio chat interface** accessible in your browser at `http://localhost:7860`.

---

## 🚀 Quick Start

### 1️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

### 2️⃣ Create your `.env` file

```env
COHERE_API_KEY=your_cohere_api_key_here
```

### 3️⃣ Ingest documents into ChromaDB (vector store)

```bash
python ingest.py
```

> This reads every `.md` file in `sample_project/`, splits them into chunks, embeds them via Cohere, and saves them to `chroma_db/`.

### 4️⃣ Extract structured data (optional but recommended)

```bash
python extract.py
```

> This uses the LLM to extract decisions, rules, warnings, dependencies, and changes from every `.md` file into `extracted_data.json`.

### 5️⃣ Run the chat app

```bash
python app.py
```

> Opens `http://localhost:7860` in your browser. Start asking questions! 🎉

---

## 📁 Project Structure

```
RAG/
├── 📄 app.py                  ← Gradio UI + startup initialization
├── ⚙️  config.py              ← All configuration (models, paths, thresholds)
├── 📥 ingest.py               ← Build the vector store from .md files
├── 🔍 extract.py              ← Extract structured JSON from .md files
├── 🗃️  structured_store.py    ← Query layer over extracted_data.json
├── 🔄 workflow.py             ← Event-driven RAG pipeline
├── 📦 requirements.txt        ← Python dependencies
│
├── 🗄️  chroma_db/             ← Persisted ChromaDB vector store
│   └── chroma.sqlite3
│
├── 📊 extracted_data.json     ← Structured JSON store (created by extract.py)
│
├── 🌐 workflow_graph.html     ← Visual diagram of the query workflow
├── 🌐 ingest_graph.html       ← Visual diagram of the ingestion workflow
│
└── 📚 sample_project/         ← Source documents (Cursor + Claude Code docs)
    ├── claude_code/
    │   ├── CLAUDE.md
    │   └── docs/
    │       ├── components.md
    │       ├── development-guide.md
    │       ├── setup.md
    │       └── testing.md
    └── cursor/
        ├── docs/
        │   ├── api-reference.md
        │   ├── architecture.md
        │   ├── deployment.md
        │   └── setup.md
        └── rules/
            ├── api-guidelines.mdc
            └── project-rules.mdc
```

---

## 🏗️ Architecture Overview

```
                        ┌──────────────────────────────────────────┐
                        │              USER (Browser)               │
                        │         http://localhost:7860             │
                        └─────────────────┬────────────────────────┘
                                          │ question (text)
                                          ▼
                        ┌──────────────────────────────────────────┐
                        │              app.py (Gradio)              │
                        │         chat_fn() → workflow.run()        │
                        └─────────────────┬────────────────────────┘
                                          │ StartEvent(question)
                                          ▼
                        ┌──────────────────────────────────────────┐
                        │           workflow.py (RAGWorkflow)        │
                        │                                           │
                        │  [1] validate_input                       │
                        │       ↓                                   │
                        │  [1b] route_query  ←── Cohere LLM         │
                        │       ↙                   ↘               │
                        │  SEMANTIC PATH        STRUCTURED PATH     │
                        │       ↓                     ↓             │
                        │  [2] retrieve          [2s] execute_       │
                        │  (ChromaDB)            structured          │
                        │       ↓               (JSON store)        │
                        │  [3] filter_results        ↓              │
                        │   ↙         ↘         [3s] synthesize_    │
                        │ above     below        structured          │
                        │ cutoff    cutoff       ←── Cohere LLM     │
                        │   ↓         ↓               ↓             │
                        │  [4] synthesize      StopEvent(answer)    │
                        │  ←── Cohere LLM                           │
                        │       ↓                                   │
                        │  [5] format_response                      │
                        │       ↓                                   │
                        │  StopEvent(answer, sources)               │
                        └──────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┴──────────────────────┐
                    │                                             │
          ┌─────────▼──────────┐                    ┌────────────▼──────────┐
          │    chroma_db/       │                    │  extracted_data.json   │
          │ (ChromaDB vectors)  │                    │ (Structured JSON store)│
          │                     │                    │                        │
          │ Built by ingest.py  │                    │  Built by extract.py   │
          └─────────────────────┘                    └────────────────────────┘
```

---

## 🔬 Module Deep-Dive

---

### ⚙️ `config.py` – Configuration Hub

The single source of truth for all tunable parameters. Reads values from a `.env` file.

```python
COHERE_API_KEY       → your API key (required)
COHERE_EMBED_MODEL   → "embed-multilingual-v3.0"   (supports Hebrew!)
COHERE_LLM_MODEL     → "command-a-03-2025"
CHROMA_PERSIST_DIR   → ./chroma_db/
CHROMA_COLLECTION_NAME → "agentic-tools-docs"
SAMPLE_PROJECT_DIR   → ./sample_project/
EXTRACTED_DATA_PATH  → ./extracted_data.json
TOP_K                → 5    (how many chunks to retrieve)
SIMILARITY_CUTOFF    → 0.30 (minimum score to keep a chunk)
```

> 💡 **Tip:** Lower `SIMILARITY_CUTOFF` if answers feel too sparse. Raise it for more focused, high-confidence answers.

---

### 📥 `ingest.py` – Ingestion Pipeline

**Purpose:** Convert raw `.md` files → embedded vector chunks → saved in ChromaDB.

#### Event Flow

```
IngestStartEvent(source_dir)
        │
        ▼
[1] validate_source ──[missing dir / no .md files]──► IngestStopEvent(error)
        │ SourceValidatedEvent
        ▼
[2] load_documents      ← reads all .md files
        │ DocumentsLoadedEvent
        ▼
[3] chunk_documents     ← splits docs into overlapping text chunks
        │ NodesCreatedEvent
        ▼
[4] build_index         ← embeds chunks via Cohere, saves to ChromaDB
        │ IngestStopEvent(stats)
```

#### What it produces

A `chroma_db/` directory containing vector embeddings for every text chunk from your documentation. Each chunk stores metadata like `tool`, `title`, `filename`, and `source_tool`.

#### Run it

```bash
python ingest.py
```

**Expected output:**
```
INFO: [validate_source] 9 .md files found
INFO: [load_documents]  9 documents loaded
INFO: [chunk_documents] 47 nodes created
INFO: [build_index]     Index built (47 nodes embedded)
```

---

### 🔍 `extract.py` – Structured Data Extractor

**Purpose:** Use the LLM to read each `.md` file and extract **structured JSON** items into 5 categories.

#### Extracted Item Types

| Category | Description | Example |
|---|---|---|
| `decisions` | Architectural/technical choices made | "Chose PostgreSQL over MongoDB" |
| `rules` | Hard constraints that must be followed | "All API routes must be versioned" |
| `warnings` | Risky areas or "do not touch" notes | "Never modify auth middleware directly" |
| `dependencies` | External libraries or services | "chromadb v0.4+" |
| `changes` | Recent updates or migrations | "Added Hebrew RTL support" |

#### Event Flow

```
StartEvent(source_dir)
        │
        ▼
[1] discover_files   ← finds all .md files
        │ FilesDiscoveredEvent
        ▼
[2] extract_files    ← LLM call per file (extracts structured JSON)
        │ AllExtractedEvent
        ▼
[3] assemble_store   ← merges all results, assigns IDs, writes to disk
        │ StopEvent(store)
        ▼
extracted_data.json
```

#### Run it

```bash
python extract.py
```

**Expected output:**
```
INFO: [discover_files] 9 .md files found
INFO: [extract_files] → components.md
INFO: [extract_files] → development-guide.md
...
INFO: [assemble_store] 87 total items
       {'decisions': 12, 'rules': 23, 'warnings': 8,
        'dependencies': 31, 'changes': 13}
       → extracted_data.json
```

#### Output Format (`extracted_data.json`)

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-03-14T10:00:00+00:00",
  "sources": [
    {
      "tool": "cursor",
      "file": "sample_project/cursor/docs/architecture.md",
      "last_modified": "2026-03-10T08:00:00+00:00",
      "hash": "sha256:abc123..."
    }
  ],
  "items": {
    "decisions": [
      {
        "id": "dec-001",
        "title": "Use PostgreSQL",
        "summary": "PostgreSQL was chosen for its JSON support and reliability.",
        "tags": ["database", "storage"],
        "source": { "tool": "cursor", "file": "..." },
        "observed_at": "2026-03-10T08:00:00+00:00"
      }
    ],
    "rules": [...],
    "warnings": [...],
    "dependencies": [...],
    "changes": [...]
  }
}
```

---

### 🗃️ `structured_store.py` – Query Layer

**Purpose:** A lightweight in-memory query interface over `extracted_data.json`. No database, no ORM – just JSON + Python dicts.

#### Available Query Methods

```python
store = StructuredStore(EXTRACTED_DATA_PATH)

# Check if data is available
store.is_available                    # → True/False

# Get all items of a type
store.get_all("decisions")            # → list of dicts

# Get all items across all types
store.get_all_items()                 # → list of dicts (with "type" field added)

# Filter by tags
store.get_by_tags(["database", "auth"])  # → items whose tags overlap

# Get recently observed items
store.get_recent(days=7)              # → items from last 7 days

# Full-text substring search
store.search_text("RTL", item_type="rules")   # → matching items

# Summary counts
store.summary()   # → {"counts": {"decisions": 12, "rules": 23, ...}}
```

---

### 🔄 `workflow.py` – RAG Query Pipeline

**Purpose:** The heart of the system. An event-driven pipeline that takes a user question and returns an (answer, sources) pair.

#### All Events

```
StartEvent              → raw question from user
InputValidatedEvent     → question passed length/content checks
SemanticRouteEvent      → router chose vector search path
StructuredRouteEvent    → router chose structured JSON path
RetrievedEvent          → ChromaDB returned raw nodes
FilteredEvent           → nodes above similarity cutoff (ready for LLM)
FallbackEvent           → all nodes below cutoff (low confidence)
SynthesizedEvent        → LLM produced an answer
StructuredResultsEvent  → structured store returned matching items
StopEvent               → final (answer, sources) tuple
```

#### Full Pipeline (Semantic Path)

```
StartEvent(question)
        │
        ▼
[1] validate_input         ← checks: not empty, 3–500 chars
        │ InputValidatedEvent
        ▼
[1b] route_query           ← LLM decides: "semantic" or "structured"
        │ SemanticRouteEvent
        ▼
[2] retrieve               ← ChromaDB top-K similarity search
        │ RetrievedEvent
        ▼
[3] filter_results         ← keep nodes with score ≥ 0.30
        ├─[≥1 node above cutoff]──► FilteredEvent(used_fallback=False)
        └─[all below cutoff]──────► FallbackEvent
                                          │
                              [3b] handle_fallback  ← uses top-3 nodes anyway
                                          │ FilteredEvent(used_fallback=True)
                                          ▼
[4] synthesize             ← Cohere LLM generates answer from context
        │ SynthesizedEvent
        ▼
[5] format_response        ← assembles (answer, sources) string
        │ StopEvent
        ▼
    (answer, sources) returned to app.py
```

#### Full Pipeline (Structured Path)

```
[1b] route_query  →  StructuredRouteEvent(query_type, item_type, ...)
        │
        ▼
[2s] execute_structured    ← queries StructuredStore (no LLM!)
        │ StructuredResultsEvent
        ▼
[3s] synthesize_structured ← Cohere LLM formats results as readable answer
        │ StopEvent
        ▼
    (answer, sources) returned to app.py
```

#### ⚠️ Fallback Warning

When the system uses the fallback path (low-confidence retrieval), it appends this note to the answer:

> ⚠️ שים לב: התשובה מבוססת על מידע בעל רלוונטיות נמוכה יחסית.
> *(Note: The answer is based on information with relatively low relevance.)*

#### Visualize the Workflow

```bash
python workflow.py   # generates workflow_graph.html
```

Open `workflow_graph.html` in your browser for an interactive diagram.

---

### 🖥️ `app.py` – Gradio Chat UI

**Purpose:** Initializes all RAG components at startup and serves the Gradio chat interface.

#### Startup Sequence

```python
1. Load .env (COHERE_API_KEY, etc.)
2. Initialize CohereEmbedding (embed-multilingual-v3.0)
3. Initialize Cohere LLM (command-a-03-2025)
4. Connect to ChromaDB collection "agentic-tools-docs"
5. Build VectorStoreIndex from ChromaDB
6. Create retriever (top_k=5)
7. Create SimilarityPostprocessor (cutoff=0.30)
8. Create response_synthesizer (mode=COMPACT)
9. Load StructuredStore from extracted_data.json
10. Start RAGWorkflow (timeout=60s)
11. Launch Gradio on http://localhost:7860
```

#### The Chat Callback

```python
async def chat_fn(message: str, history: list) -> str:
    answer, sources = await workflow.run(question=message)
    if sources:
        return f"{answer}\n\n---\n**מקורות:**\n{sources}"
    return answer
```

Every message triggers the full RAGWorkflow pipeline and returns the formatted answer with source attribution.

---

## 🔀 The Dual-Path Routing System

One of the most powerful features is the **automatic routing** between two retrieval strategies:

```
                     User Question
                           │
                           ▼
               ┌───────────────────────┐
               │   Cohere LLM Router   │
               │   (ROUTING_PROMPT)    │
               └───────────┬───────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
      🔵 SEMANTIC PATH          🟠 STRUCTURED PATH
   (vector similarity)          (JSON query engine)
              │                         │
              ▼                         ▼
       ChromaDB lookup          StructuredStore
       Top-5 similar chunks     .get_all() / .get_recent()
       → Cohere LLM → answer    .search_text() / .get_by_tags()
                                → Cohere LLM → answer
```

### Router Decision Logic

The LLM reads `ROUTING_PROMPT` and returns JSON like:

```json
// Semantic route:
{"route": "semantic"}

// Structured route:
{
  "route": "structured",
  "query_type": "all_type",
  "item_type": "decisions",
  "tags": [],
  "days": null,
  "search_text": null
}
```

### Query Types (Structured Path)

| `query_type` | When Used | Example Question |
|---|---|---|
| `all_type` | "List all X" | "Show all the project rules" |
| `recent` | Time-based | "What changed in the last 7 days?" |
| `tags` | Tag filtering | "Find items tagged 'security'" |
| `text_search` | Keyword search | "Rules mentioning RTL" |

---

## 💬 Example Questions & What Happens

### Example 1 – "How do I install the system?" 🔵 Semantic

```
User: "איך מתקינים את המערכת?"

Route: semantic
  → ChromaDB finds: setup.md chunks (similarity ~0.82)
  → filter_results: 3 nodes above 0.30 cutoff
  → synthesize: Cohere generates installation steps
  → format_response: adds source attribution

Answer: "כדי להתקין את המערכת:
1. Clone the repository...
2. pip install -r requirements.txt
3. ...

---
**מקורות:**
• Cursor – setup.md (0.82)
• Claude Code – setup.md (0.76)"
```

---

### Example 2 – "List all technical decisions" 🟠 Structured

```
User: "תן לי רשימה של כל ההחלטות הטכניות"

Route: structured (query_type=all_type, item_type=decisions)
  → execute_structured: store.get_all("decisions") → 12 items
  → synthesize_structured: Cohere formats as numbered list

Answer: "הנה כל ההחלטות הטכניות שתועדו בפרויקט:

1. **בחירת PostgreSQL** – נבחר בשל תמיכה טובה ב-JSON ואמינות גבוהה
2. **ניהול גרסאות API** – כל מסלולי ה-API מגיע עם קידומת /v1/
3. **אימות מבוסס JWT** – נבחר לפשטות ותאימות עם לקוחות SPA
...

---
**מקורות:**
• Cursor – architecture.md
• Claude Code – components.md"
```

---

### Example 3 – "What are all the warnings?" 🟠 Structured

```
User: "אילו אזהרות קיימות במערכת"

Route: structured (query_type=all_type, item_type=warnings)
  → execute_structured: store.get_all("warnings") → 8 items
  → synthesize_structured: formatted with severity levels

Answer: "⚠️ אזהרות קריטיות:
• [HIGH] Database migrations – אל תשנה ידנית את migration files
• [HIGH] Auth middleware – כל שינוי עלול לשבור את מנגנון ה-JWT
...

⚠️ אזהרות בינוניות:
• [MEDIUM] Rate limiting – הגבלות קצב מוחלות ב-production בלבד
..."
```

---

### Example 4 – Low Confidence Fallback ⚠️

```
User: "What is the meaning of life?"

Route: semantic (no structured match possible)
  → ChromaDB: 5 nodes returned, scores: [0.21, 0.18, 0.15, 0.12, 0.09]
  → filter_results: ALL below 0.30 cutoff → FallbackEvent
  → handle_fallback: uses top-3 nodes anyway
  → synthesize: Cohere generates best-effort answer

Answer: "לא נמצא מידע ישיר לשאלה זו בתיעוד...

⚠️ שים לב: התשובה מבוססת על מידע בעל רלוונטיות נמוכה יחסית."
```

---

## 📚 The Sample Project

The `sample_project/` directory contains documentation for a fictional **Task Manager API** project, organized for two agentic coding tools:

### 🖱️ Cursor Docs (`sample_project/cursor/`)

| File | Content |
|---|---|
| `docs/api-reference.md` | Full REST API endpoint documentation |
| `docs/architecture.md` | System design and component overview |
| `docs/deployment.md` | Deployment guide (Docker, env vars) |
| `docs/setup.md` | Local development setup |
| `rules/api-guidelines.mdc` | Cursor-specific API coding rules |
| `rules/project-rules.mdc` | General project constraints |

### 🤖 Claude Code Docs (`sample_project/claude_code/`)

| File | Content |
|---|---|
| `CLAUDE.md` | High-level project context for Claude |
| `docs/components.md` | Component breakdown and responsibilities |
| `docs/development-guide.md` | Development workflow guide |
| `docs/setup.md` | Environment setup instructions |
| `docs/testing.md` | Testing strategy and test running |

> 💡 Replace this sample project with **your own documentation** to make the system answer questions about YOUR project!

---

## 🔄 Data Flows – Step by Step

### 📥 Ingestion Flow (run once before using the app)

```
sample_project/
   *.md files
       │
       │ llama-index FileReader
       ▼
   raw Document objects
       │
       │ SentenceSplitter (chunking + overlap)
       ▼
   TextNode objects (chunks)
       │
       │ CohereEmbedding.get_text_embedding_batch()
       │ model: embed-multilingual-v3.0
       ▼
   float[] vectors (1024 dimensions each)
       │
       │ ChromaVectorStore.add()
       ▼
   chroma_db/
   (persisted on disk)
```

### 🔍 Query Flow (every user question)

```
User types question
       │
       ▼
validate_input (length: 3–500 chars)
       │
       ▼
route_query (Cohere LLM reads ROUTING_PROMPT)
       │
   ┌───┴────┐
   │        │
   ▼        ▼
SEMANTIC  STRUCTURED
   │        │
   ▼        ▼
ChromaDB  StructuredStore
top-5     .get_all()
nodes     .search_text()
   │      .get_recent()
   │        │
   ▼        ▼
filter    (no filter needed –
results    structured data is
           already exact)
   │        │
   ▼        ▼
Cohere    Cohere
LLM       LLM
(COMPACT  (STRUCTURED_
 mode)    SYNTHESIS_PROMPT)
   │        │
   └───┬────┘
       │
       ▼
  (answer, sources)
       │
       ▼
  Gradio UI → User
```

---

## ⚙️ Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `COHERE_API_KEY` | *(required)* | Your Cohere API key |
| `COHERE_EMBED_MODEL` | `embed-multilingual-v3.0` | Embedding model (supports Hebrew) |
| `COHERE_LLM_MODEL` | `command-a-03-2025` | Generation model |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Where ChromaDB stores its data |
| `CHROMA_COLLECTION_NAME` | `agentic-tools-docs` | ChromaDB collection name |
| `SAMPLE_PROJECT_DIR` | `./sample_project` | Source `.md` files directory |
| `EXTRACTED_DATA_PATH` | `./extracted_data.json` | Structured store output path |
| `TOP_K` | `5` | Number of chunks to retrieve from ChromaDB |
| `SIMILARITY_CUTOFF` | `0.30` | Min similarity score (0.0–1.0) to pass filtering |

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `llama-index-core` | Workflow engine, VectorStoreIndex, event system |
| `llama-index-embeddings-cohere` | Cohere embedding integration |
| `llama-index-llms-cohere` | Cohere LLM integration |
| `llama-index-vector-stores-chroma` | ChromaDB vector store adapter |
| `llama-index-readers-file` | Markdown file loader |
| `chromadb` | Local persistent vector database |
| `cohere` | Official Cohere Python SDK |
| `gradio` | Web chat UI framework |
| `python-dotenv` | Load API keys from `.env` file |
| `truststore` | Fix SSL certificate issues on Windows |
| `pyvis` | Generate interactive workflow HTML graphs |

---

## 🛠️ Useful Commands

```bash
# Rebuild vector store (after adding new .md files)
python ingest.py

# Rebuild structured JSON store (after changing docs)
python extract.py

# Generate visual workflow diagram
python workflow.py         # → workflow_graph.html

# Run the chat app
python app.py              # → http://localhost:7860
```

---

## 🧩 How to Use With Your Own Docs

1. **Replace** the contents of `sample_project/` with your own `.md` documentation
2. **Run** `python ingest.py` to embed them into ChromaDB
3. **Run** `python extract.py` to extract structured knowledge
4. **Run** `python app.py` and start chatting!

> 📝 **Note:** Both `cursor/` and `claude_code/` subdirectory names are used as the `tool` metadata field in the vector store. You can name your subfolders anything – they'll show up in the source attribution.

---

*Generated: March 14, 2026 | Model: Cohere command-a-03-2025 | Embeddings: embed-multilingual-v3.0*
