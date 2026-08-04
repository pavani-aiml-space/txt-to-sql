"""The generic LLM client: which provider to use, built once and reused.

Purpose: pick and build the right LLM client from whatever key is
configured. Kept separate from nlq/text_to_sql.py so "which AI service to
call" doesn't mix with "what to ask it." Works by checking env vars for an
Azure or OpenAI key and constructing (and caching) the matching client.
"""

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_llm():
    """Returns a LangChain chat model if credentials are configured, else None.

    Cached (one process, built once): without this, every question would
    build a brand-new client -- and its underlying HTTP connection -- from
    scratch, paying a fresh TLS handshake each time instead of reusing one."""
    try:
        if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
            from langchain_openai import AzureChatOpenAI

            return AzureChatOpenAI(
                azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                temperature=0,
            )
        if os.getenv("OPENAI_API_KEY"):
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
    except Exception:
        return None
    return None
