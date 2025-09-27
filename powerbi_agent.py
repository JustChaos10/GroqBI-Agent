import re
import pandas as pd

# Optional LLM support
try:
    from langchain_core.prompts import PromptTemplate
    from groq_manager import LangChainGroqManager
except Exception:
    PromptTemplate = None
    LangChainGroqManager = None


class PowerBIAgent:
    """Generates DAX / explains results with optional LLM; safe fallbacks included."""

    def __init__(self):
        self.llm = None
        if LangChainGroqManager:
            try:
                self.llm = LangChainGroqManager().get_llm_model()
            except Exception as e:
                print(f"⚠️ LLM unavailable: {e}")

    # ---------- DAX generation ----------
    def dax_generator(self, user_question: str, database_schema: str) -> str:
        """
        Return one DAX query to answer user_question given database_schema.
        Falls back to a stable test query if no LLM.
        """
        fallback = 'EVALUATE ROW("Result", 1)'

        if not self.llm or not PromptTemplate:
            return fallback

        try:
            template = PromptTemplate.from_template(
                """You are a DAX expert. Given the semantic model schema:

{schema}

Write ONE valid DAX query (for XMLA) that best answers:
{question}

CRITICAL:
- Output ONLY the query, no commentary.
- Use EVALUATE and return a table (add TOPN if needed).
- If unsure, return: EVALUATE ROW("Result", 1)
"""
            )
            prompt = template.format(schema=database_schema, question=user_question)
            result = self.llm.invoke(prompt)

            # ChatGroq returns a dict with 'content' or a string
            text = result.get("content") if isinstance(result, dict) else str(result)
            text = re.sub(r"```[\s\S]*?```", "", text).strip()
            return text if "EVALUATE" in text.upper() else fallback
        except Exception as e:
            print(f"⚠️ DAX generation failed: {e}")
            return fallback

    # ---------- Natural language explanation ----------
    def nl_response(self, user_question: str, df: pd.DataFrame) -> str:
        """Turn a small DataFrame result into a one-paragraph answer."""
        if df is None or df.empty:
            return "I didn't get any rows back from the model."

        preview = df.head(5).to_dict(orient="records")
        cols = list(df.columns)
        return f"Top {len(preview)} rows for {cols}: " + "; ".join(str(r) for r in preview)
