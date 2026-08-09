import re
import html
import random
import datetime
import streamlit as st
import pandas as pd
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_CLARIFYING_ROUNDS = 3

CONFIRM_PROMPTS = [
    "This is what I understand to be the primary issues. Is this correct and complete?",
    "Here's what I'm hearing as the main picture. Does that look right, and is anything missing?",
    "This is how I'm reading the note so far. Have I captured it correctly, and is there anything to add?",
    "Here's what stands out to me as the key points. Does this match your read, and is it complete?",
    "This is my understanding of what matters most here. Is that accurate, and have I left anything out?",
    "Here's the gist of what I'm taking from this. Correct me if I've got something wrong or missed something.",
]

TIER_MAP = {
    "Let ARIA decide": None,
    "Tier 1 - Quick confirmation": 1,
    "Tier 2 - Explore options": 2,
    "Tier 3 - Deep teaching": 3,
}

VIEWS = ["Executive Chart", "Scribe Tool", "Graphical Analysis", "Literature & Evidence"]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def split_question(text: str):
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
    return k.replace("_", " ").strip().capitalize()


def _format_value(v):
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
    """Soft summary card in place of raw JSON."""
    skip = {"error"}
    rows = []
    for k, v in (parsed or {}).items():
        if k in skip:
            continue
        fv = _format_value(v)
        if fv:
            rows.append((_humanize_key(k), fv))

    if not rows:
        st.info("I couldn't pull additional structured details from this note.")
        return

    lead_html = f'<div class="aria-sum-lead">{html.escape(lead)}</div>' if lead else ""
    row_html = "".join(
        f'<div class="aria-sum-row">'
        f'<span class="aria-sum-label">{html.escape(label)}</span>'
        f'<span class="aria-sum-val">{html.escape(value)}</span>'
        f'</div>'
        for label, value in rows
    )
    st.markdown(f'<div class="aria-summary">{lead_html}{row_html}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Standardized-measure extraction (for the Graphical Analysis tab)
# ---------------------------------------------------------------------------
def extract_metrics(text: str):
    """Return a list of {measure, result, max, pct, detail} pulled from the note."""
    if not text:
        return []
    t = text.replace("\u2013", "-").replace("\u2014", "-")
    found = []

    def add(measure, result, max_score=None, detail=""):
        pct = None
        try:
            if max_score:
                num = float(str(result).split("/")[0])
                pct = round(num / float(max_score) * 100)
        except Exception:
            pct = None
        found.append({"measure": measure, "result": str(result),
                      "max": max_score, "pct": pct, "detail": detail})

    m = re.search(r"(?:Berg Balance(?:\s*Scale)?|BBS)\D{0,20}?(\d{1,3})\s*/\s*(\d{1,3})", t, re.I)
    if m:
        add("Berg Balance Scale (BBS)", f"{m.group(1)}/{m.group(2)}", int(m.group(2)),
            "High fall risk below 45")

    m = re.search(r"(?:Fugl-?Meyer[^\d/]{0,30}|FMA[-\s]?UE\D{0,12})(\d{1,3})\s*/\s*(\d{1,3})", t, re.I)
    if m:
        add("Fugl-Meyer Upper Extremity (FMA-UE)", f"{m.group(1)}/{m.group(2)}", int(m.group(2)),
            "Lower score = more severe motor impairment")

    m = re.search(r"(?:10[-\s]?Meter Walk Test|10MWT|gait speed)\D{0,25}?(\d+(?:\.\d+)?)\s*m\s*/?\s*s", t, re.I)
    if m:
        add("10-Meter Walk Test (10MWT)", f"{m.group(1)} m/s", None,
            "Community ambulation typically >0.8 m/s")

    m = re.search(r"(?:Timed Up (?:and|&) Go|TUG)\D{0,20}?(\d+(?:\.\d+)?)\s*s", t, re.I)
    if m:
        add("Timed Up and Go (TUG)", f"{m.group(1)} s", None, "Fall risk often >13.5 s")

    m = re.search(r"(?:6[-\s]?Minute Walk Test|6MWT)\D{0,20}?(\d+(?:\.\d+)?)\s*m\b", t, re.I)
    if m:
        add("6-Minute Walk Test (6MWT)", f"{m.group(1)} m", None, "Endurance / distance")

    for gm in re.finditer(r"Grade\s*([0-4]\+?)\s*(?:in\s*)?([A-Za-z][A-Za-z /]+?)(?=[;.\n]|$)", t, re.I):
        add("Modified Ashworth", f"Grade {gm.group(1)}", None, gm.group(2).strip())

    for bm in re.finditer(r"(Right|Left)?\s*(UE|LE|Upper Extremity|Lower Extremity)[:\s]*Stage\s*([1-7])", t, re.I):
        side = (bm.group(1) or "").strip()
        limb = bm.group(2).upper().replace("UPPER EXTREMITY", "UE").replace("LOWER EXTREMITY", "LE")
        label = f"{side} {limb}".strip()
        add("Brunnstrom Stage", f"Stage {bm.group(3)}", None, label)

    return found


# ---------------------------------------------------------------------------
# Patient-case model (in-session; swap-in a database later without UI changes)
# ---------------------------------------------------------------------------
def blank_case(cid, name):
    return {
        "id": cid,
        "name": name or cid,
        "created": datetime.datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "note": "",
        "parsed": None,
        "metrics": [],
        "confirm_prompt": "",
        "confirmed": False,
        "tier_choice_value": None,
        "clarifications": [],
        "pending_question": None,
        "literature": None,
        "responded": False,
        "response_error": None,
        "tier_used": None,
        "tier_rationale": None,
        "conversation": [],
    }


def ensure_state():
    if "cases" not in st.session_state:
        st.session_state.cases = {}
        st.session_state.case_order = []
        st.session_state.case_counter = 0
        st.session_state.name_nonce = 0
    if "view" not in st.session_state:
        st.session_state.view = "Scribe Tool"


def create_case(name):
    st.session_state.case_counter += 1
    cid = f"CASE-{st.session_state.case_counter:04d}"
    st.session_state.cases[cid] = blank_case(cid, name)
    st.session_state.case_order.append(cid)
    st.session_state.case_picker = cid
    return cid


def active_case():
    cid = st.session_state.get("case_picker")
    if cid and cid in st.session_state.cases:
        return st.session_state.cases[cid]
    return None


# ---------------------------------------------------------------------------
# Literature search helpers
# ---------------------------------------------------------------------------
def advance_search(case):
    """One search attempt: either sets literature, or sets a clarifying question."""
    literature = retrieve_literature_smart(case["note"], case["parsed"], case["clarifications"])
    if literature.get("sources") or len(case["clarifications"]) >= MAX_CLARIFYING_ROUNDS:
        case["literature"] = literature
    else:
        case["pending_question"] = generate_clarifying_question(
            case["note"], case["parsed"], case["clarifications"]
        )


def finalize_response(case):
    literature = case["literature"]
    result = generate_response(case["parsed"], literature, case["note"], tier=case["tier_choice_value"])
    case["responded"] = True
    if result.get("tier_used") is None:
        case["tier_used"] = None
        case["response_error"] = result.get("response_text", "ARIA could not generate a response.")
        return
    case["tier_used"] = result["tier_used"]
    case["tier_rationale"] = result.get("tier_rationale")
    case["conversation"] = [
        {"role": "user", "content": case["note"]},
        {"role": "assistant", "content": result["response_text"]},
    ]
    log_interaction({
        "type": "initial_response",
        "case_id": case["id"],
        "note": case["note"],
        "clarifications": case["clarifications"],
        "search_query": literature.get("query_used"),
        "tier_used": result["tier_used"],
        "tier_rationale": result.get("tier_rationale"),
        "response": result["response_text"],
    })


# ---------------------------------------------------------------------------
# Sidebar: patient case manager
# ---------------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown("### Patients")
        nonce = st.session_state.get("name_nonce", 0)
        new_name = st.text_input("New patient (name or label)",
                                 key=f"new_case_name_{nonce}",
                                 placeholder="e.g., Vance, E.")
        if st.button("Add patient case", width="stretch"):
            create_case(new_name.strip())
            st.session_state.name_nonce = nonce + 1
            st.session_state.view = "Scribe Tool"
            st.rerun()

        order = st.session_state.get("case_order", [])
        if order:
            st.markdown("---")
            st.caption("Open a case")
            labels = {cid: f"{st.session_state.cases[cid]['name']}  ·  {cid}" for cid in order}
            prev = st.session_state.get("case_picker")
            chosen = st.radio(
                "Open a case",
                order,
                format_func=lambda c: labels[c],
                key="case_picker",
                label_visibility="collapsed",
            )
            if chosen != prev:
                st.rerun()
        else:
            st.caption("No patients yet. Add one above to begin.")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def render_scribe(case):
    st.markdown(f"##### Scribe Tool  ·  {case['name']}")
    st.write("Enter or dictate the clinical note. ARIA will read it back for your confirmation before doing anything else.")

    note_key = f"note_{case['id']}"
    if note_key not in st.session_state:
        st.session_state[note_key] = case.get("note", "")
    note_val = st.text_area("Clinical note", key=note_key, height=220)
    case["note"] = note_val

    tkey = f"tier_{case['id']}"
    tier_choice = st.selectbox("Response style", list(TIER_MAP.keys()), key=tkey)
    case["tier_choice_value"] = TIER_MAP[tier_choice]

    if st.button("Have ARIA read it", key=f"read_{case['id']}"):
        if not note_val.strip():
            st.warning("Please enter the note first.")
        else:
            with st.spinner("ARIA is reading the note..."):
                parsed = parse_clinician_note(note_val)
            if parsed.get("error"):
                st.error(parsed["error"])
            else:
                case["parsed"] = parsed
                case["metrics"] = extract_metrics(note_val)
                case["confirm_prompt"] = random.choice(CONFIRM_PROMPTS)
                case["confirmed"] = False
                case["clarifications"] = []
                case["pending_question"] = None
                case["literature"] = None
                case["responded"] = False
                case["response_error"] = None
                case["tier_used"] = None
                case["conversation"] = []
                st.rerun()

    if case["parsed"] and not case["confirmed"]:
        st.write("")
        st.markdown(f"**{case['confirm_prompt']}**")
        render_clinical_summary(case["parsed"])
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Yes, that's correct", key=f"yes_{case['id']}"):
                case["confirmed"] = True
                st.session_state._goto_view = "Literature & Evidence"
                st.rerun()
        with c2:
            if st.button("No, let me adjust something", key=f"no_{case['id']}"):
                case["parsed"] = None
                st.rerun()
    elif case["confirmed"]:
        st.success("ARIA has confirmed its read of this note. Open Literature & Evidence for guidance, or the Executive Chart for the overview.")
        render_clinical_summary(case["parsed"])


def render_executive(case):
    st.markdown("##### Executive Chart")
    parsed = case.get("parsed") or {}
    dx = _format_value(parsed.get("diagnosis")) or "Not yet determined"
    st.markdown(
        f'<div class="aria-patient">'
        f'<div class="pname">{html.escape(case["name"])}</div>'
        f'<div class="pmeta">{html.escape(case["id"])} &nbsp;·&nbsp; created {html.escape(case["created"])}</div>'
        f'<div class="pdx"><b>Working diagnosis:</b> {html.escape(dx)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if not case["parsed"]:
        st.info("This case is new. Start in the Scribe Tool to enter the note.")
        return

    if case.get("metrics"):
        chips = "".join(
            f'<span class="aria-chip"><b>{html.escape(m["measure"].split("(")[0].strip())}:</b> {html.escape(m["result"])}</span>'
            for m in case["metrics"][:6]
        )
        st.markdown(f'<div class="aria-chips">{chips}</div>', unsafe_allow_html=True)

    st.markdown("**ARIA's read of the case**")
    render_clinical_summary(case["parsed"])

    aria_msgs = [t["content"] for t in case.get("conversation", []) if t["role"] == "assistant"]
    if aria_msgs:
        main, q = split_question(aria_msgs[-1])
        st.markdown("**ARIA's latest guidance**")
        st.markdown(main[:700] + ("..." if len(main) > 700 else ""))
        if q:
            st.info(f"**ARIA is asking:** {q}")
    else:
        st.caption("No ARIA guidance yet. Open Literature & Evidence and run the search.")


def render_graphical(case):
    st.markdown("##### Graphical Analysis")
    if not case["parsed"]:
        st.info("Enter and confirm a note in the Scribe Tool first.")
        return

    metrics = case.get("metrics") or []
    if not metrics:
        st.info("ARIA did not detect standardized measures in this note. As measures are added to the record, they will appear here as tables and charts.")
        return

    df = pd.DataFrame([
        {"Measure": m["measure"],
         "Result": m["result"],
         "Site / notes": m["detail"]}
        for m in metrics
    ])
    st.dataframe(df, hide_index=True, width="stretch")

    pct_rows = [m for m in metrics if m["pct"] is not None]
    if pct_rows:
        chart_df = pd.DataFrame(
            {"Percent of maximum": [m["pct"] for m in pct_rows]},
            index=[m["measure"] for m in pct_rows],
        )
        st.bar_chart(chart_df)
        st.caption("Scored measures shown as a percent of their maximum score. As this case is reassessed over time, this is where progress trends will appear.")


def render_literature(case):
    st.markdown("##### Literature & Evidence")
    if not case["confirmed"]:
        st.info("Confirm ARIA's read of the note in the Scribe Tool first.")
        return

    # 1) Not started yet
    if case["literature"] is None and not case["pending_question"]:
        st.write("ARIA will search PubMed for evidence relevant to this case, then respond as a mentor calibrated to your chosen level of detail.")
        if st.button("Search the literature", key=f"search_{case['id']}"):
            with st.spinner("Searching medical literature..."):
                advance_search(case)
            st.rerun()
        return

    # 2) Awaiting a clarifying answer
    if case["pending_question"]:
        st.info(f"ARIA is refining the search ({len(case['clarifications']) + 1} of {MAX_CLARIFYING_ROUNDS}).")
        st.markdown(f"**ARIA is asking:** {case['pending_question']}")
        ans = st.text_input("Your answer", key=f"clar_{case['id']}_{len(case['clarifications'])}")
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Submit answer", key=f"clarsub_{case['id']}"):
                if ans.strip():
                    case["clarifications"].append({"question": case["pending_question"], "answer": ans})
                    case["pending_question"] = None
                    with st.spinner("Refining the search..."):
                        advance_search(case)
                    st.rerun()
                else:
                    st.warning("Enter an answer, or skip.")
        with c2:
            if st.button("Skip and proceed", key=f"clarskip_{case['id']}"):
                literature = retrieve_literature_smart(case["note"], case["parsed"], case["clarifications"])
                literature["note"] = "No matching literature was found even after clarifying questions. ARIA will respond using clinical reasoning alone."
                case["literature"] = literature
                case["pending_question"] = None
                st.rerun()
        return

    # 3) Literature is set; generate ARIA's response once
    if not case["responded"]:
        with st.spinner("Preparing ARIA's response..."):
            finalize_response(case)
        st.rerun()

    if case["response_error"]:
        st.error(case["response_error"])
        if st.button("Try again", key=f"retry_{case['id']}"):
            case["literature"] = None
            case["responded"] = False
            case["response_error"] = None
            st.rerun()
        return

    # 4) Show ARIA's response + conversation
    literature = case["literature"]
    if literature.get("note"):
        st.info(literature["note"])
    st.markdown(f"**Response tier:** {case['tier_used']}")
    st.divider()

    for turn in case["conversation"]:
        if turn["role"] == "assistant":
            with st.chat_message("assistant"):
                render_aria_message(turn["content"])
        else:
            with st.chat_message("user"):
                st.markdown(turn["content"])

    num_sources = len(literature.get("sources", []))
    with st.expander(f"About the literature ({num_sources} source(s) found)"):
        st.markdown("**Source:** PubMed, via the National Library of Medicine's NCBI database")
        if literature.get("query_used"):
            st.markdown(f"**Search query used:**\n```\n{literature['query_used']}\n```")
        if literature.get("rationale"):
            st.markdown(f"**Why these terms:** {literature['rationale']}")
        if case["clarifications"]:
            st.markdown("**Clarifying questions used to refine the search:**")
            for c in case["clarifications"]:
                st.markdown(f"- *{c['question']}* -> {c['answer']}")
        if literature.get("note"):
            st.info(literature["note"])
        for source in literature.get("sources", []):
            st.markdown(f"**{source['title']}** (PMID: {source['pmid']})")
            st.write(source["abstract"])

    st.divider()
    follow_up = st.text_input("Respond to ARIA, ask a question, or share your thinking:", key=f"follow_{case['id']}")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Send", key=f"send_{case['id']}"):
            if follow_up.strip():
                case["conversation"].append({"role": "user", "content": follow_up})
                with st.spinner("ARIA is thinking..."):
                    reply = continue_conversation(case["conversation"], case["tier_used"])
                case["conversation"].append({"role": "assistant", "content": reply})
                log_interaction({
                    "type": "follow_up",
                    "case_id": case["id"],
                    "tier_used": case["tier_used"],
                    "clinician_message": follow_up,
                    "aria_reply": reply,
                })
                st.rerun()
            else:
                st.warning("Please enter a message before sending.")
    with c2:
        if st.button("Re-run the search", key=f"rerun_{case['id']}"):
            case["literature"] = None
            case["responded"] = False
            case["response_error"] = None
            case["clarifications"] = []
            case["pending_question"] = None
            case["conversation"] = []
            case["tier_used"] = None
            st.rerun()

    st.divider()
    st.caption("How did this interaction go?")
    feedback = st.radio(
        "Feedback:",
        options=["Very helpful", "Somewhat helpful", "Not helpful", "Confusing"],
        horizontal=True,
        index=None,
        key=f"fb_{case['id']}",
    )
    feedback_notes = st.text_input("Anything ARIA got wrong, or that was unclear? (optional)", key=f"fbn_{case['id']}")
    if st.button("Submit feedback", key=f"fbsub_{case['id']}"):
        if feedback:
            log_interaction({
                "type": "feedback",
                "case_id": case["id"],
                "tier_used": case["tier_used"],
                "rating": feedback,
                "notes": feedback_notes,
            })
            st.success("Thanks, feedback logged.")
        else:
            st.warning("Please select a rating first.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ensure_state()
render_sidebar()

case = active_case()
if case is None:
    st.markdown("#### Welcome to the ARIA workspace")
    st.write(
        "Add a patient case in the panel on the left to begin. Each case keeps its own note, "
        "ARIA's read of it, the literature, and your conversation, so you can move between "
        "patients and pick up right where you left off."
    )
    st.stop()

if "_goto_view" in st.session_state:
    st.session_state.view = st.session_state.pop("_goto_view")

view = st.radio("Workspace", VIEWS, horizontal=True, key="view", label_visibility="collapsed")
st.divider()

if view == "Executive Chart":
    render_executive(case)
elif view == "Scribe Tool":
    render_scribe(case)
elif view == "Graphical Analysis":
    render_graphical(case)
elif view == "Literature & Evidence":
    render_literature(case)
