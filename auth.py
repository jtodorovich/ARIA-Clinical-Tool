import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _get_credential(key: str) -> str:
    """
    Checks Streamlit Cloud secrets first (for the deployed version),
    then falls back to local .env (for running on your own computer).
    """
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, "")


def require_login():
    """
    Shows a login form and halts the rest of the app until the
    correct username and password are entered. Call this at the
    very top of app.py, before anything else runs.
    """
    if st.session_state.get("authenticated"):
        return

    st.title("ARIA")
    st.subheader("Adaptive Rehabilitation Intelligence Assistant")
    st.write("Please log in to continue.")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Log in"):
        correct_username = _get_credential("PILOT_USERNAME")
        correct_password = _get_credential("PILOT_PASSWORD")

        if username == correct_username and password == correct_password and correct_username:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect username or password.")

    st.stop()
