"""
ARIA branding
=============
Self-contained visual identity for ARIA. No external image files needed:
the ARIA mark is embedded directly below. app.py imports three things from
here: PAGE_ICON, inject_style, and render_header.
"""

import streamlit as st

# ARIA mark, embedded as a data URI (used for the browser tab icon and header).
PAGE_ICON = "data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgMjU2IDI1NiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiByb2xlPSJpbWciIGFyaWEtbGFiZWw9IkFSSUEiPgogIDxkZWZzPgogICAgPGxpbmVhckdyYWRpZW50IGlkPSJ0aWxlIiB4MT0iMCIgeTE9IjAiIHgyPSIxIiB5Mj0iMSI+CiAgICAgIDxzdG9wIG9mZnNldD0iMCIgc3RvcC1jb2xvcj0iIzBFM0E0NiIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjAuNTUiIHN0b3AtY29sb3I9IiMxNTVDNkIiLz4KICAgICAgPHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjMUU3QThDIi8+CiAgICA8L2xpbmVhckdyYWRpZW50PgogICAgPGxpbmVhckdyYWRpZW50IGlkPSJzdHJva2UiIHgxPSIwIiB5MT0iMSIgeDI9IjEiIHkyPSIwIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwIiBzdG9wLWNvbG9yPSIjNTdDNEM5Ii8+CiAgICAgIDxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iI0VBRjdGNyIvPgogICAgPC9saW5lYXJHcmFkaWVudD4KICAgIDxyYWRpYWxHcmFkaWVudCBpZD0ic3BhcmsiIGN4PSIwLjUiIGN5PSIwLjUiIHI9IjAuNSI+CiAgICAgIDxzdG9wIG9mZnNldD0iMCIgc3RvcC1jb2xvcj0iI0ZCRTZBRSIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjAuNTUiIHN0b3AtY29sb3I9IiNFOEIwNEIiLz4KICAgICAgPHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjRThCMDRCIiBzdG9wLW9wYWNpdHk9IjAiLz4KICAgIDwvcmFkaWFsR3JhZGllbnQ+CiAgPC9kZWZzPgoKICA8cmVjdCB4PSIwIiB5PSIwIiB3aWR0aD0iMjU2IiBoZWlnaHQ9IjI1NiIgcng9IjYwIiBmaWxsPSJ1cmwoI3RpbGUpIi8+CgogIDxjaXJjbGUgY3g9IjEyOCIgY3k9IjEyOCIgcj0iODYiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzU3QzRDOSIgc3Ryb2tlLW9wYWNpdHk9IjAuMTYiIHN0cm9rZS13aWR0aD0iOCIvPgoKICA8cGF0aCBkPSJNIDc4IDE5MiBMIDEzMiA3OCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ1cmwoI3N0cm9rZSkiIHN0cm9rZS13aWR0aD0iMTUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgoKICA8cGF0aCBkPSJNIDE3OCAxOTIgQyAxNzYgMTUwLCAxNjggMTE2LCAxNTAgODQiIGZpbGw9Im5vbmUiIHN0cm9rZT0idXJsKCNzdHJva2UpIiBzdHJva2Utd2lkdGg9IjE1IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KCiAgPHBhdGggZD0iTSAxMDIgMTUwIEwgMTY4IDE1MCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjRUFGN0Y3IiBzdHJva2Utb3BhY2l0eT0iMC43IiBzdHJva2Utd2lkdGg9IjExIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz4KCiAgPGNpcmNsZSBjeD0iMTQxIiBjeT0iNzQiIHI9IjM0IiBmaWxsPSJ1cmwoI3NwYXJrKSIvPgogIDxjaXJjbGUgY3g9IjE0MSIgY3k9Ijc0IiByPSIxMi41IiBmaWxsPSIjRjRDODYzIi8+CiAgPGNpcmNsZSBjeD0iMTQxIiBjeT0iNzQiIHI9IjEyLjUiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI0ZCRTZBRSIgc3Ryb2tlLXdpZHRoPSIyLjUiLz4KPC9zdmc+Cg=="

PALETTE = {
    "petrol": "#0E3A46", "teal": "#1E7A8C", "aqua": "#57C4C9",
    "gold": "#E8B04B", "ink": "#12262B", "mist": "#E8F1F2",
}


def inject_style():
    """Fonts, colors, and header styling. Call once, right after
    st.set_page_config()."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] { font-family: 'Inter', -apple-system, Segoe UI, sans-serif; }

        /* Page background — aimed at the app container so it actually takes,
           with a tint that is clearly not white. */
        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewContainer"] > .main,
        .stApp,
        body { background-color: #E8F1F2 !important; }
        [data-testid="stHeader"] { background: transparent !important; }

        h1, h2, h3, h4 { color: #0E3A46 !important; font-weight: 700; letter-spacing: 0.2px; }
        a { color: #155C6B; }

        /* teal buttons (covers normal buttons and form submit buttons) */
        .stButton > button, .stFormSubmitButton > button {
            background-color: #1E7A8C !important; color: #FFFFFF !important; border: none !important;
            border-radius: 8px !important; font-weight: 600 !important; padding: 0.45rem 1.1rem !important;
        }
        .stButton > button:hover, .stFormSubmitButton > button:hover { background-color: #155C6B !important; }

        /* cleaner product feel: hide the default menu + footer.
           Delete these two lines if you ever want them back. */
        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }

        /* ARIA note-summary card */
        .aria-summary {
            background:#FFFFFF; border:1px solid #CBDEDE; border-left:4px solid #1E7A8C;
            border-radius:10px; padding:14px 18px;
        }
        .aria-sum-lead { color:#0E3A46; font-weight:600; margin-bottom:10px; }
        .aria-sum-row { display:flex; gap:14px; padding:6px 0; border-top:1px solid #EEF4F4; }
        .aria-sum-row:first-of-type { border-top:none; }
        .aria-sum-label { flex:0 0 160px; color:#155C6B; font-weight:600; font-size:13.5px; }
        .aria-sum-val { color:#12262B; font-size:14px; line-height:1.5; }

        /* ARIA header band */
        .aria-hero {
            display: flex; align-items: center; gap: 18px;
            background: linear-gradient(105deg, #0E3A46 0%, #155C6B 55%, #1E7A8C 100%);
            border-radius: 16px; padding: 22px 30px; margin: 0 0 16px 0;
            border-bottom: 3px solid #E8B04B;
            box-shadow: 0 6px 20px rgba(14,58,70,0.18);
        }
        .aria-hero img { width: 78px; height: 78px; flex: 0 0 auto; }
        .aria-hero .word { font-weight: 700; font-size: 46px; letter-spacing: 5px; color: #FFFFFF; line-height: 1.02; }
        .aria-hero .tag { font-size: 18.5px; font-weight: 500; color: #9FD9DC; margin-top: 4px; }
        .aria-hero .val { font-size: 14px; color: #CDEBEC; margin-top: 6px; opacity: 0.92; }
        /* patient header card (Executive Chart) */
        .aria-patient { background:#FFFFFF; border:1px solid #CBDEDE; border-left:4px solid #E8B04B;
            border-radius:12px; padding:16px 20px; margin-bottom:14px; }
        .aria-patient .pname { font-size:20px; font-weight:700; color:#0E3A46; }
        .aria-patient .pmeta { font-size:13px; color:#5A7A80; margin-top:2px; }
        .aria-patient .pdx { font-size:14px; color:#12262B; margin-top:10px; }
        .aria-patient .pdx b { color:#155C6B; }
        /* metric chips */
        .aria-chips { display:flex; flex-wrap:wrap; gap:10px; margin:4px 0 12px; }
        .aria-chip { background:#EAF3F4; border:1px solid #CBDEDE; border-radius:999px;
            padding:6px 14px; font-size:13px; color:#12262B; }
        .aria-chip b { color:#155C6B; }
        /* workspace nav (radio rendered as a tab bar) */
        div[data-testid="stRadio"] div[role="radiogroup"] { gap:4px; border-bottom:2px solid #CBDEDE; }
        div[data-testid="stRadio"] div[role="radiogroup"] > label { padding:8px 16px; margin-bottom:-2px; border-radius:8px 8px 0 0; }
        div[data-testid="stRadio"] div[role="radiogroup"] > label:hover { background:#EAF3F4; }

        /* input contrast: make fields stand out from the tinted page */
        .stTextInput input, .stTextArea textarea, .stNumberInput input {
            background-color:#FFFFFF !important; border:1px solid #A9C9CD !important;
            border-radius:8px !important; box-shadow:0 1px 2px rgba(14,58,70,0.06) !important;
        }
        .stTextInput input:focus, .stTextArea textarea:focus {
            border-color:#1E7A8C !important; box-shadow:0 0 0 3px rgba(30,122,140,0.18) !important;
        }
        [data-baseweb="select"] > div { background-color:#FFFFFF !important; border-color:#A9C9CD !important; }
        [data-baseweb="base-input"] { background-color:#FFFFFF !important; }
        /* ARIA speaking directly to the user */
        .aria-ask { display:flex; align-items:flex-start; gap:12px; background:#FFFFFF;
            border:1px solid #CBDEDE; border-left:4px solid #1E7A8C; border-radius:10px;
            padding:14px 16px; margin:6px 0; }
        .aria-ask img { width:34px; height:34px; flex:0 0 auto; margin-top:1px; }
        .aria-ask .q { color:#0E3A46; font-size:15px; font-weight:600; line-height:1.5; }

        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(value_line="Your clinical thinking partner for rehabilitation decisions."):
    """The ARIA header band. Call once, near the top of the page."""
    st.markdown(
        f'''
        <div class="aria-hero">
            <img src="{PAGE_ICON}" alt="ARIA"/>
            <div>
                <div class="word">ARIA</div>
                <div class="tag">Adaptive Rehabilitation Intelligence Assistant</div>
                <div class="val">{value_line}</div>
            </div>
        </div>
        ''',
        unsafe_allow_html=True,
    )
