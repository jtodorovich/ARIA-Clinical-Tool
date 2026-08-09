import re
import html
import random
import streamlit as st
from branding import PAGE_ICON, inject_style, render_header

st.set_page_config(page_title="ARIA", page_icon=PAGE_ICON, layout="wide")
inject_style()
render_header()

from auth import require_login

require_login()
from intake import parse_clinician_note
from rag import retrieve_literature_smart, generate_clarifying_question
from literacy_engine import generate_response, continue_conversation
from log import log_interaction

MAX_CLARIFYING_ROUNDS = 3

# ARIA's confirmation line varies a little each time, so it reads like a person
# checking in rather than a template.
CONFIRM_PROMPTS = [
    "This is what I understand to be the primary issues. Is this correct and complete?",
    "Here's what I'm hearing as the main picture. Does that look right, and is anything missing?",
    "This is how I'm reading the note so far. Have I captured it correctly, and is there anything to add?",
    "Here's what stands out to me as the key points. Does this match your read, and is it complete?",
    "This is my understanding of what matters most here. Is that accurate, and have I left anything out?",
    "Here's the gist of what I'm taking from this. Correct me if I've got something wrong or missed something.",
]


def split_question(text: str):
    """
    Splits ARIA's response into (main_text, question) if a
    '**Question for you:**' marker is present. Returns (text, None)
    if no marker is found.
    """
    match = re.search(r"\*\*Question for you:\*\*\s*(.+)", text, re.DOTALL)
    if match:
        question = match.group(1).strip()
        main_text = text[:match.start()].strip()
        return main_text, question
    return text, None


def render_aria_message(text: str):
    main_text, question = split_question(text)
    st.markdown(main_text)
    if question:
        st.info(f"**ARIA is asking:** {question}")


def _humanize_key(k: str) -> str:
    """Turn a field name like 'chief_complaint' into 'Chief complaint'."""
    return k.replace("_", " ").strip().capitalize()


def _format_value(v):
    """Render a parsed value as clean readable text, or None if empty."""
    if isinstance(v, (list, tuple)):
        items = [str(x).strip() for x in v if str(x).strip()]
        return ", ".join(items) if items else None
    if isinstance(v, dict):
        parts = []
        for kk, vv in v.items():
            fv = _format_value(vv)
            if fv:
                parts.append(f"{_humanize_key(kk)}: {fv}")
        return "; ".join(parts) if parts else None
    s = str(v).strip()
    if not s or s.lower() in ("none", "null", "n/a", "na", "unknown", "not specified"):
        return None
    return s


def render_clinical_summary(parsed: dict, lead: str = None):
    """Show ARIA's read of the note as a soft summary card instead of raw JSON."""
    skip = {"error"}
    rows = []
    for k, v in parsed.items():
        if k in skip:
            continue
        fv = _format_value(v)
        if fv:
            rows.append((_humanize_key(k), fv))

    if not rows:
        st.info("I couldn't pull additional structured details from this note.")
        return

    row_html = "".join(
        f'<div class="aria-sum-row">'
        f'<span class="aria-sum-label">{html.escape(label)}</span>'
        f'<span class="aria-sum-val">{html.escape(value)}</span>'
        f'</div>'
        for label, value in rows
    )
    lead_html = f'<div class="aria-sum-lead">{html.escape(lead)}</div>' if lead else ""
    st.markdown(
        f'<div class="aria-summary">{lead_html}{row_html}</div>',
        unsafe_allow_html=True,
    )


if "stage" not in st.session_state:
    st.session_state.stage = "intake"
    st.session_state.conversation = []
    st.session_state.tier_used = None
    st.session_state.parsed = None
    st.session_state.literature = None
    st.session_state.original_note = None
    st.session_state.tier_choice_value = None
    st.session_state.clarifications = []


def reset_case():
    st.session_state.stage = "intake"
    st.session_state.conversation = []
    st.session_state.tier_used = None
    st.session_state.parsed = None
    st.session_state.literature = None
    st.session_state.original_note = None
    st.session_state.tier_choice_value = None
    st.session_state.clarifications = []
    st.session_state.pop("note_input", None)


tier_map = {
    "Let ARIA decide": None,
    "Tier 1 - Quick confirmation": 1,
    "Tier 2 - Explore options": 2,
    "Tier 3 - Deep teaching": 3,
}

# ---------- STAGE: intake ----------
if st.session_state.stage == "intake":
    st.write("Enter a clinician note below. ARIA will confirm the diagnosis, pull relevant literature, and respond as a mentor calibrated to your preferred level of detail.")

    clinician_note = st.text_area("Enter a clinician note or query:", key="note_input")
    tier_choice = st.selectbox("Response style:", options=list(tier_map.keys()))

    if st.button("Submit"):
        if not clinician_note or not clinician_note.strip():
            st.warning("Please enter some text before submitting.")
        else:
            with st.spinner("Analyzing note..."):
                parsed = parse_clinician_note(clinician_note)

            if parsed.get("error"):
                st.error(parsed["error"])
            else:
                st.session_state.parsed = parsed
                st.session_state.original_note = clinician_note
                st.session_state.tier_choice_value = tier_map[tier_choice]
                st.session_state.clarifications = []
                st.session_state.confirm_prompt = random.choice(CONFIRM_PROMPTS)
                st.session_state.stage = "confirm"
                st.rerun()

# ---------- STAGE: confirm (clinician verifies ARIA's read) ----------
elif st.session_state.stage == "confirm":
    prompt = st.session_state.get("confirm_prompt", CONFIRM_PROMPTS[0])
    st.markdown(f"**{prompt}**")
    render_clinical_summary(st.session_state.parsed)

    st.write("")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Yes, that's correct"):
            st.session_state.stage = "searching"
            st.rerun()
    with c2:
        if st.button("No, let me adjust something"):
            st.session_state.note_input = st.session_state.original_note
            st.session_state.stage = "intake"
            st.rerun()

# ---------- STAGE: searching (with clarifying loop) ----------
elif st.session_state.stage == "searching":
    with st.spinner("Searching medical literature..."):
        literature = retrieve_literature_smart(
            st.session_state.original_note,
            st.session_state.parsed,
            st.session_state.clarifications,
        )

    if literature["sources"] or len(st.session_state.clarifications) >= MAX_CLARIFYING_ROUNDS:
        st.session_state.literature = literature
        st.session_state.stage = "respond" if literature["sources"] else "give_up_and_respond"
        st.rerun()
    else:
        with st.spinner("Refining the search..."):
            question = generate_clarifying_question(
                st.session_state.original_note,
                st.session_state.parsed,
                st.session_state.clarifications,
            )
        st.session_state.pending_question = question
        st.session_state.stage = "awaiting_clarification"
        st.rerun()

# ---------- STAGE: awaiting_clarification ----------
elif st.session_state.stage == "awaiting_clarification":
    st.info(f"ARIA is having trouble finding targeted literature. To help narrow the search ({len(st.session_state.clarifications) + 1} of {MAX_CLARIFYING_ROUNDS}):")
    st.markdown(f"**ARIA is asking:** {st.session_state.pending_question}")
    answer = st.text_input("Your answer:")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Submit answer"):
            if answer and answer.strip():
                st.session_state.clarifications.append({
                    "question": st.session_state.pending_question,
                    "answer": answer,
                })
                st.session_state.stage = "searching"
                st.rerun()
            else:
                st.warning("Please enter an answer, or choose to skip below.")
    with col2:
        if st.button("Skip and proceed with best available information"):
            st.session_state.stage = "give_up_and_respond"
            st.rerun()

# ---------- STAGE: give_up_and_respond ----------
elif st.session_state.stage == "give_up_and_respond":
    literature = retrieve_literature_smart(
        st.session_state.original_note,
        st.session_state.parsed,
        st.session_state.clarifications,
    )
    literature["note"] = "No matching literature was found even after clarifying questions. ARIA will respond using clinical reasoning alone."
    st.session_state.literature = literature
    st.session_state.stage = "respond"
    st.rerun()

# ---------- STAGE: respond ----------
elif st.session_state.stage == "respond":
    literature = st.session_state.literature
    if literature.get("note"):
        st.info(literature["note"])

    with st.spinner("Preparing response..."):
        result = generate_response(
            st.session_state.parsed,
            literature,
            st.session_state.original_note,
            tier=st.session_state.tier_choice_value,
        )

    if result.get("tier_used") is None:
        st.error(result["response_text"])
        if st.button("Start over"):
            reset_case()
            st.rerun()
    else:
        st.session_state.tier_used = result["tier_used"]
        st.session_state.conversation = [
            {"role": "user", "content": st.session_state.original_note},
            {"role": "assistant", "content": result["response_text"]},
        ]
        log_interaction({
            "type": "initial_response",
            "note": st.session_state.original_note,
            "clarifications": st.session_state.clarifications,
            "search_query": literature.get("query_used"),
            "tier_used": result["tier_used"],
            "tier_rationale": result["tier_rationale"],
            "response": result["response_text"],
        })
        st.session_state.stage = "conversation"
        st.rerun()

# ---------- STAGE: conversation ----------
elif st.session_state.stage == "conversation":
    st.markdown(f"**Response tier:** {st.session_state.tier_used}")
    st.divider()

    for turn in st.session_state.conversation:
        role_label = "You" if turn["role"] == "user" else "ARIA"
        with st.chat_message("user" if turn["role"] == "user" else "assistant"):
            if turn["role"] == "assistant":
                st.markdown(f"**{role_label}:**")
                render_aria_message(turn["content"])
            else:
                st.markdown(f"**{role_label}:** {turn['content']}")

    with st.expander("ARIA's summary of the note", expanded=True):
        render_clinical_summary(st.session_state.parsed)

    literature = st.session_state.literature
    num_sources = len(literature.get("sources", []))
    with st.expander(f"About the literature ({num_sources} source(s) found)"):
        st.markdown("**Source:** PubMed, via the National Library of Medicine's NCBI database")
        if literature.get("query_used"):
            st.markdown(f"**Search query used:**\n```\n{literature['query_used']}\n```")
        if literature.get("rationale"):
            st.markdown(f"**Why these terms:** {literature['rationale']}")
        if st.session_state.clarifications:
            st.markdown("**Clarifying questions used to refine the search:**")
            for c in st.session_state.clarifications:
                st.markdown(f"- *{c['question']}* -> {c['answer']}")
        if literature.get("note"):
            st.info(literature["note"])
        for source in literature.get("sources", []):
            st.markdown(f"**{source['title']}** (PMID: {source['pmid']})")
            st.write(source["abstract"])

    st.divider()
    follow_up = st.text_input("Respond to ARIA, ask a question, or share your thinking:")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Send"):
            if follow_up and follow_up.strip():
                st.session_state.conversation.append({"role": "user", "content": follow_up})
                with st.spinner("ARIA is thinking..."):
                    reply = continue_conversation(st.session_state.conversation, st.session_state.tier_used)
                st.session_state.conversation.append({"role": "assistant", "content": reply})

                log_interaction({
                    "type": "follow_up",
                    "tier_used": st.session_state.tier_used,
                    "clinician_message": follow_up,
                    "aria_reply": reply,
                })
                st.rerun()
            else:
                st.warning("Please enter a message before sending.")
    with col2:
        if st.button("Start a new case"):
            reset_case()
            st.rerun()

    st.divider()
    st.caption("How did this interaction go?")
    feedback = st.radio(
        "Feedback:",
        options=["Very helpful", "Somewhat helpful", "Not helpful", "Confusing"],
        horizontal=True,
        index=None,
        key="feedback_radio",
    )
    feedback_notes = st.text_input("Anything ARIA got wrong, or that was unclear? (optional)")

    if st.button("Submit feedback"):
        if feedback:
            log_interaction({
                "type": "feedback",
                "tier_used": st.session_state.tier_used,
                "rating": feedback,
                "notes": feedback_notes,
            })
            st.success("Thanks, feedback logged.")
        else:
            st.warning("Please select a rating first.")
