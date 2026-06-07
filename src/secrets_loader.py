"""
Unified secrets loader: reads from .env locally AND from Streamlit Cloud secrets in production.

Streamlit Cloud doesn't use .env — it expects secrets in .streamlit/secrets.toml
configured via the web UI. This helper tries both sources transparently so the
same code works locally and in production.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def get_secret(key: str, default: str = "") -> str:
    """
    Retrieve a secret value. Order of precedence:
      1. Streamlit Cloud secrets (if running inside Streamlit)
      2. Environment variable (.env or shell)
      3. Provided default
    """
    # Try Streamlit secrets first (only works when called from within Streamlit context)
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass

    return os.getenv(key, default)
