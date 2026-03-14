"""
app.py – RAG Chat Application (Gradio)
=======================================
Exposes a chat interface where users can ask questions about the Agentic Coding
tool documentation that was indexed by ingest.py.

Query pipeline (event-driven – see workflow.py):
  StartEvent → validate_input → retrieve → filter_results
                                                ├── [above cutoff] → FilteredEvent
                                                └── [below cutoff] → FallbackEvent → handle_fallback
                                                                            ↓
                                                                        synthesize (LLM)
                                                                            ↓
                                                                       format_response → StopEvent

Run:
  python app.py
"""

# SSL fix for Windows / Python 3.14: inject system certificate store
import truststore
truststore.inject_into_ssl()

import logging

import chromadb
import gradio as gr
from dotenv import load_dotenv

from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.response_synthesizers import get_response_synthesizer, ResponseMode
from llama_index.embeddings.cohere import CohereEmbedding
from llama_index.llms.cohere import Cohere
from llama_index.vector_stores.chroma import ChromaVectorStore

from config import (
    COHERE_API_KEY,
    COHERE_EMBED_MODEL,
    COHERE_LLM_MODEL,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    TOP_K,
    SIMILARITY_CUTOFF,
)
from workflow import RAGWorkflow

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ── Initialise RAG components (once at startup) ───────────────────────────────

def _init_workflow() -> RAGWorkflow:
    """
    Build all RAG components and wrap them in the event-driven RAGWorkflow.
    """
    embed_model = CohereEmbedding(
        api_key=COHERE_API_KEY,
        model_name=COHERE_EMBED_MODEL,
        input_type="search_query",
    )
    llm = Cohere(
        api_key=COHERE_API_KEY,
        model=COHERE_LLM_MODEL,
    )
    Settings.embed_model = embed_model
    Settings.llm = llm

    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    chroma_collection = chroma_client.get_collection(CHROMA_COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

    retriever = index.as_retriever(similarity_top_k=TOP_K)
    postprocessor = SimilarityPostprocessor(similarity_cutoff=SIMILARITY_CUTOFF)
    response_synthesizer = get_response_synthesizer(
        response_mode=ResponseMode.COMPACT,
        llm=llm,
    )

    return RAGWorkflow(
        retriever=retriever,
        postprocessor=postprocessor,
        response_synthesizer=response_synthesizer,
        timeout=60,
    )


logger.info("Initialising RAG workflow …")
workflow = _init_workflow()
logger.info("RAG workflow ready.")


# ── Gradio UI ─────────────────────────────────────────────────────────────────

async def chat_fn(message: str, history: list) -> str:
    """
    Gradio chat callback.
    Delegates to the event-driven RAGWorkflow and formats the output.
    """
    answer, sources = await workflow.run(question=message)
    if sources:
        return f"{answer}\n\n---\n**מקורות:**\n{sources}"
    return answer


with gr.Blocks(title="RAG – Agentic Coding Docs") as demo:
    gr.Markdown(
        """
        # 🔍 RAG – מאגר ידע Agentic Coding
        שאל שאלות על כלי **Cursor** ו-**Claude Code** ועל הפרויקט Task Manager API.

        המערכת מחפשת סמנטית בתיעוד, מאחזרת את הקטעים הרלוונטיים ביותר,
        ומנסחת תשובה מפורטת בעזרת Cohere Command-R+.
        """
    )

    gr.ChatInterface(
        fn=chat_fn,
        examples=[
            "איך מתקינים את המערכת?",
            "מה הארכיטקטורה של הפרויקט?",
            "איך מריצים את הטסטים?",
            "מהי מדיניות האימות (Authentication) של ה-API?",
            "איך מגדירים משתני סביבה לפיתוח מקומי?",
            "איך מוסיפים Migration חדש לבסיס הנתונים?",
            "מה קורה כשמישהו שולח בקשה לא מאומתת?",
            "איך מבצעים Deployment לפרודקשן?",
        ],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, theme=gr.themes.Soft())
