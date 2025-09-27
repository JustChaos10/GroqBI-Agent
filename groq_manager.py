import os
from dotenv import load_dotenv

try:
    from langchain_groq import ChatGroq
except Exception:
    ChatGroq = None

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except Exception:
    HuggingFaceEmbeddings = None


class LangChainGroqManager:
    """Tiny wrapper around Groq + optional HF embeddings."""

    def __init__(self):
        load_dotenv()

        self.model_name = os.environ.get("MODEL_ID_LLM", "llama-3.3-70b-versatile")
        self.model_fallback = os.environ.get("MODEL_ID_LLM_ALTERNATIVE", "llama-3.1-8b-instant")
        self.api_key = os.environ.get("GROQ_API_KEY", "")

        self.langchain_groq_llm = None
        self.langchain_embeddings = None

        # LLM (optional)
        if ChatGroq and self.api_key:
            try:
                self.langchain_groq_llm = ChatGroq(
                    model=self.model_name,
                    temperature=0.1,
                    max_tokens=2048,
                    api_key=self.api_key,
                )
                print(f"✅ Groq LLM ready: {self.model_name}")
            except Exception as e:
                print(f"⚠️ Groq init failed ({e}); trying fallback…")
                try:
                    self.langchain_groq_llm = ChatGroq(
                        model=self.model_fallback,
                        temperature=0.1,
                        max_tokens=2048,
                        api_key=self.api_key,
                    )
                    print(f"✅ Groq fallback ready: {self.model_fallback}")
                except Exception as e2:
                    print(f"⚠️ Groq fallback failed: {e2}. Continuing without LLM.")
        else:
            print("ℹ️ Groq not configured; continuing without LLM.")

        # Embeddings (optional)
        if HuggingFaceEmbeddings:
            try:
                emb_model = os.environ.get("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
                self.langchain_embeddings = HuggingFaceEmbeddings(model_name=emb_model)
                print(f"✅ HF embeddings ready: {emb_model}")
            except Exception as e:
                print(f"⚠️ HF embeddings init failed: {e}")

    def get_llm_model(self):
        return self.langchain_groq_llm
