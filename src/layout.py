"""
Shared layout helpers so every page has the same compact styling.
Import and call inject_compact_css() at the top of each page.
"""
import streamlit as st


COMPACT_CSS = """
<style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1400px !important;
    }
    header[data-testid="stHeader"] { height: 0 !important; background: transparent; }
    [data-testid="stToolbar"] { display: none; }

    [data-testid="stMetricValue"] {
        font-size: 1.2rem !important; font-weight: 700;
        color: #FAFAFA; line-height: 1.2;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.65rem !important; color: #9CA3AF;
        text-transform: uppercase; letter-spacing: 0.04em; line-height: 1.1;
    }
    [data-testid="stMetricDelta"] { font-size: 0.7rem !important; }

    .stCaption, [data-testid="stCaptionContainer"] {
        font-size: 0.72rem !important; line-height: 1.2;
    }

    h1 { font-size: 1.4rem !important; margin-top: 0.25rem !important; margin-bottom: 0.25rem !important; }
    h2 { font-size: 1.05rem !important; margin-top: 0.6rem !important; margin-bottom: 0.4rem !important; }
    h3 { font-size: 0.9rem !important; margin-top: 0.5rem !important; margin-bottom: 0.3rem !important; }

    [data-testid="stSidebar"] .stCaption { font-size: 0.7rem !important; }
    [data-testid="stDataFrame"] { font-size: 0.78rem; }
    hr { margin: 0.5rem 0 !important; }
</style>
"""


def inject_compact_css():
    st.markdown(COMPACT_CSS, unsafe_allow_html=True)
