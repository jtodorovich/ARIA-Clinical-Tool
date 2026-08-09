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
    "Quick check": 1,
    "Explore options": 2,
    "Deep teaching": 3,
}

LEVEL_DESCRIPTIONS = {
    "Let ARIA decide": "I'll choose the depth based on your note.",
    "Quick check": "I'll confirm the diagnosis and surface the key evidence, briefly.",
    "Explore options": "I'll walk through the main options and what the research shows.",
    "Deep teaching": "I'll give a fuller teaching response with the reasoning explained.",
}

V_OVERVIEW = "Overview"
V_INTAKE = "Intake"
V_MEASURES = "Measures & Trends"
V_EVIDENCE = "Evidence & Guidance"
VIEWS = [V_OVERVIEW, V_INTAKE, V_MEASURES, V_EVIDENCE]

# Optional guided-intake questions. All skippable.
INTAKE_FIELDS = [
    ("age_sex", "Age and sex", "e.g., 67-year-old male"),
    ("diagnosis", "Primary problem or diagnosis", "e.g., left MCA ischemic stroke, right hemiparesis"),
    ("history", "Brief history / onset", "e.g., 12 weeks post-stroke, moving to outpatient"),
    ("goals", "Patient goals", "e.g., walk to the mailbox; self-feed with right hand"),
    ("precautions", "Safety concerns or precautions", "e.g., two near-falls this week; foot drop"),
    ("measures", "Key standardized measures", "e.g., BBS 38/56; 10MWT 0.35 m/s; FMA-UE 22/66"),
    ("medications", "Current medications", "e.g., Baclofen 10 mg TID; Clopidogrel 75 mg"),
    ("focus", "What would you like my help with?", "e.g., prioritizing gait vs. UE work"),
]


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


def render_aria_question(text: str):
    """Render a question as ARIA speaking directly to the clinician."""
    st.markdown(
        f'<div class="aria-ask"><img src="{PAGE_ICON}" alt="ARIA"/>'
        f'<div class="q">{html.escape(text)}</div></div>',
        unsafe_allow_html=True,
    )


def render_aria_message(text: str):
    main_text, question = split_question(text)
    st.markdown(main_text)
    if question:
        render_aria_question(question)


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


def render_level_selector(case):
    """Prominent, always-visible choice of how much detail ARIA gives."""
    with st.container(border=True):
        st.markdown("**How would you like ARIA to work with you?**")
        choice = st.radio(
            "ARIA level",
            list(TIER_MAP.keys()),
            key=f"tier_{case['id']}",
            horizontal=True,
            label_visibility="collapsed",
        )
        case["tier_choice_value"] = TIER_MAP[choice]
        st.caption(LEVEL_DESCRIPTIONS.get(choice, ""))


def compose_note(name, answers):
    order = [
        ("age_sex", "Age/Sex"),
        ("diagnosis", "Primary problem / diagnosis"),
        ("history", "History"),
        ("goals", "Patient goals"),
        ("precautions", "Safety / precautions"),
        ("measures", "Standardized measures"),
        ("medications", "Current medications"),
        ("focus", "Requested focus"),
    ]
    lines = []
    if name:
        lines.append(f"Patient: {name}")
    for k, label in order:
        v = (answers.get(k) or "").strip()
        if v:
            lines.append(f"{label}: {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standardized-measure extraction (Measures & Trends tab)
# ---------------------------------------------------------------------------
def extract_metrics(text: str):
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
# Patient-case model (in-session)
# ---------------------------------------------------------------------------
def blank_case(cid, name):
    return {
        "id": cid,
        "name": name or cid,
        "created": datetime.datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "edit_rev": 0,
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
        st.session_state.view = V_INTAKE


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
# Literature helpers
# ---------------------------------------------------------------------------
def advance_search(case):
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
        case["response_error"] = result.get("response_text", "I wasn't able to generate a response.")
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
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown("### Patients")
        nonce = st.session_state.get("name_nonce", 0)
        new_name = st.text_input("New patient (name or label)",
                                 key=f"new_case_name_{nonce}",
                                 placeholder="e.g., Vance, E.")
        if st.button("Add patient", width="stretch"):
            create_case(new_name.strip())
            st.session_state.name_nonce = nonce + 1
            st.session_state.view = V_INTAKE
            st.rerun()

        order = st.session_state.get("case_order", [])
        if order:
            st.markdown("---")
            st.caption("Open a patient")
            labels = {cid: f"{st.session_state.cases[cid]['name']}  ·  {cid}" for cid in order}
            prev = st.session_state.get("case_picker")
            chosen = st.radio(
                "Open a patient",
                order,
                format_func=lambda c: labels[c],
                key="case_picker",
                label_visibility="collapsed",
            )
            if chosen != prev:
                st.rerun()
        else:
            st.caption("No patients yet. Add one above to begin.")

        st.markdown("---")
        with st.expander("How to use ARIA"):
            st.markdown(
                "- **Add a patient** above; each keeps its own note, chart, and our conversation.\n"
                "- **Intake**: paste a note or answer a few quick questions, pick how much detail you want, "
                "then have me read it back to confirm.\n"
                "- **Evidence & Guidance**: I search PubMed and talk it through; reply to me with follow-ups.\n"
                "- **Overview**: the chart at a glance; use *Edit patient details* to change the name or any field.\n"
                "- **Measures & Trends**: standardized measures as a table and chart.\n"
                "- Practice and synthetic data only for this pilot."
            )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def render_intake(case):
    st.markdown(f"##### Intake · {case['name']}")
    st.write("I can work from a note you already have, or we can build the picture together. Both are optional, so do whichever is easier.")

    render_level_selector(case)

    with st.expander("Build the note with a few quick questions (all optional)", expanded=not case.get("note")):
        st.caption("Answer whatever you know and skip the rest. I'll draft a note from your answers that you can edit before I read it back.")
        gnk = f"gname_{case['id']}"
        if gnk not in st.session_state:
            st.session_state[gnk] = case["name"]
        st.text_input("Patient name or label", key=gnk)
        answers = {}
        for fkey, label, ph in INTAKE_FIELDS:
            answers[fkey] = st.text_input(label, key=f"g_{fkey}_{case['id']}", placeholder=ph)
        if st.button("Draft the note from these answers", key=f"gbuild_{case['id']}"):
            composed = compose_note(st.session_state[gnk].strip(), answers)
            if not composed.strip():
                st.warning("Add at least one detail above, or just type a note below.")
            else:
                if st.session_state[gnk].strip():
                    case["name"] = st.session_state[gnk].strip()
                case["note"] = composed
                st.session_state.pop(f"note_{case['id']}", None)  # let the note box re-seed
                st.rerun()

    note_key = f"note_{case['id']}"
    if note_key not in st.session_state:
        st.session_state[note_key] = case.get("note", "")
    note_val = st.text_area("Clinical note", key=note_key, height=220)
    case["note"] = note_val

    if st.button("Read it back to me", key=f"read_{case['id']}"):
        if not note_val.strip():
            st.warning("Please add the note first.")
        else:
            with st.spinner("Reading the note..."):
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
                st.session_state._goto_view = V_EVIDENCE
                st.rerun()
        with c2:
            if st.button("No, let me adjust something", key=f"no_{case['id']}"):
                case["parsed"] = None
                st.rerun()
    elif case["confirmed"]:
        st.success("Great, I've got the picture. Open Evidence & Guidance for my take, or the Overview for the chart.")
        render_clinical_summary(case["parsed"])


def render_executive(case):
    st.markdown("##### Overview")
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

    with st.expander("Edit patient details"):
        enk = f"editname_{case['id']}"
        if enk not in st.session_state:
            st.session_state[enk] = case["name"]
        st.text_input("Patient name or label", key=enk)

        base_rows = [{"Field": _humanize_key(k), "Value": _format_value(v) or ""}
                     for k, v in parsed.items() if k != "error"]
        if not base_rows:
            base_rows = [{"Field": "", "Value": ""}]
        edited = st.data_editor(
            pd.DataFrame(base_rows),
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            key=f"edit_tbl_{case['id']}_{case.get('edit_rev', 0)}",
        )
        st.caption("Edit a value, rename a field, add a row, or delete one. Then save.")
        if st.button("Save changes", key=f"savep_{case['id']}"):
            case["name"] = st.session_state[enk].strip() or case["name"]
            newp = {}
            for _, r in edited.iterrows():
                fld = str(r.get("Field", "")).strip()
                val = str(r.get("Value", "")).strip()
                if fld:
                    newp[fld.lower().replace(" ", "_")] = val
            if newp:
                case["parsed"] = newp
            case["edit_rev"] = case.get("edit_rev", 0) + 1
            st.success("Saved.")
            st.rerun()

    if not case["parsed"]:
        st.info("This patient is new. Head to the Intake tab to get started.")
        return

    if case.get("metrics"):
        chips = "".join(
            f'<span class="aria-chip"><b>{html.escape(m["measure"].split("(")[0].strip())}:</b> {html.escape(m["result"])}</span>'
            for m in case["metrics"][:6]
        )
        st.markdown(f'<div class="aria-chips">{chips}</div>', unsafe_allow_html=True)

    st.markdown("**The picture so far**")
    render_clinical_summary(case["parsed"])

    aria_msgs = [t["content"] for t in case.get("conversation", []) if t["role"] == "assistant"]
    if aria_msgs:
        main, q = split_question(aria_msgs[-1])
        st.markdown("**My latest guidance**")
        st.markdown(main[:700] + ("..." if len(main) > 700 else ""))
        if q:
            render_aria_question(q)
    else:
        st.caption("We haven't gotten to my guidance yet. Head to Evidence & Guidance and I'll pull the evidence.")


def render_graphical(case):
    st.markdown("##### Measures & Trends")
    if not case["parsed"]:
        st.info("Add and confirm a note in the Intake tab first.")
        return

    metrics = case.get("metrics") or []
    if not metrics:
        st.info("I didn't detect standardized measures in this note. As measures are added to the record, they'll appear here as tables and charts.")
        return

    df = pd.DataFrame([
        {"Measure": m["measure"], "Result": m["result"], "Site / notes": m["detail"]}
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
        st.caption("Scored measures shown as a percent of their maximum. As this patient is reassessed over time, this is where progress trends will appear.")


def render_literature(case):
    st.markdown("##### Evidence & Guidance")
    if not case["confirmed"]:
        st.info("Let's confirm the note in the Intake tab first, then I'll pull the evidence.")
        return

    if case["literature"] is None and not case["pending_question"]:
        render_level_selector(case)
        st.write("I'll search PubMed for evidence relevant to this patient, then talk it through with you at the level you chose above.")
        if st.button("Find the evidence", key=f"search_{case['id']}"):
            with st.spinner("Searching the medical literature..."):
                advance_search(case)
            st.rerun()
        return

    if case["pending_question"]:
        st.caption(f"Let me narrow this down ({len(case['clarifications']) + 1} of {MAX_CLARIFYING_ROUNDS}).")
        render_aria_question(case["pending_question"])
        ans = st.text_input("Your answer", key=f"clar_{case['id']}_{len(case['clarifications'])}")
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Send answer", key=f"clarsub_{case['id']}"):
                if ans.strip():
                    case["clarifications"].append({"question": case["pending_question"], "answer": ans})
                    case["pending_question"] = None
                    with st.spinner("Refining the search..."):
                        advance_search(case)
                    st.rerun()
                else:
                    st.warning("Type an answer, or skip.")
        with c2:
            if st.button("Skip and proceed", key=f"clarskip_{case['id']}"):
                literature = retrieve_literature_smart(case["note"], case["parsed"], case["clarifications"])
                literature["note"] = "I couldn't find closely matching literature even after those questions, so I'll reason from clinical principles."
                case["literature"] = literature
                case["pending_question"] = None
                st.rerun()
        return

    if not case["responded"]:
        with st.spinner("Putting my thoughts together..."):
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

    literature = case["literature"]
    if literature.get("note"):
        st.info(literature["note"])
    st.caption(f"Detail level: {case['tier_used']}")
    st.divider()

    for turn in case["conversation"]:
        if turn["role"] == "assistant":
            with st.chat_message("assistant"):
                render_aria_message(turn["content"])
        else:
            with st.chat_message("user"):
                st.markdown(turn["content"])

    num_sources = len(literature.get("sources", []))
    with st.expander(f"The evidence I used ({num_sources} source(s))"):
        st.markdown("**Source:** PubMed, via the National Library of Medicine's NCBI database")
        if literature.get("query_used"):
            st.markdown(f"**Search I ran:**\n```\n{literature['query_used']}\n```")
        if literature.get("rationale"):
            st.markdown(f"**Why these terms:** {literature['rationale']}")
        if case["clarifications"]:
            st.markdown("**What I asked to narrow the search:**")
            for c in case["clarifications"]:
                st.markdown(f"- *{c['question']}* -> {c['answer']}")
        if literature.get("note"):
            st.info(literature["note"])
        for source in literature.get("sources", []):
            st.markdown(f"**{source['title']}** (PMID: {source['pmid']})")
            st.write(source["abstract"])

    st.divider()
    follow_up = st.text_input("Reply to me, ask a question, or share your thinking:", key=f"follow_{case['id']}")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Send", key=f"send_{case['id']}"):
            if follow_up.strip():
                case["conversation"].append({"role": "user", "content": follow_up})
                with st.spinner("Thinking..."):
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
                st.warning("Please type a message before sending.")
    with c2:
        if st.button("Search again", key=f"rerun_{case['id']}"):
            case["literature"] = None
            case["responded"] = False
            case["response_error"] = None
            case["clarifications"] = []
            case["pending_question"] = None
            case["conversation"] = []
            case["tier_used"] = None
            st.rerun()

    st.divider()
    st.caption("How did this go?")
    feedback = st.radio(
        "Feedback:",
        options=["Very helpful", "Somewhat helpful", "Not helpful", "Confusing"],
        horizontal=True,
        index=None,
        key=f"fb_{case['id']}",
    )
    feedback_notes = st.text_input("Anything I got wrong, or that was unclear? (optional)", key=f"fbn_{case['id']}")
    if st.button("Submit feedback", key=f"fbsub_{case['id']}"):
        if feedback:
            log_interaction({
                "type": "feedback",
                "case_id": case["id"],
                "tier_used": case["tier_used"],
                "rating": feedback,
                "notes": feedback_notes,
            })
            st.success("Thanks, that's logged.")
        else:
            st.warning("Please pick a rating first.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ensure_state()
render_sidebar()

case = active_case()
if case is None:
    st.markdown("#### Welcome to ARIA")
    st.write("I'm ARIA, your clinical thinking partner for rehabilitation. Here's how we'll work together.")
    st.markdown(
        "1. **Add a patient** in the panel on the left. Give a name or label and I'll assign a case number.\n"
        "2. **Intake** — paste a note you already have, or answer a few quick questions and I'll draft one for you. "
        "This is also where you choose **how much detail you want from me**.\n"
        "3. I'll **read the note back** so you can confirm I've understood it before going further.\n"
        "4. **Evidence & Guidance** — I search PubMed and talk it through as a mentor. Ask me follow-up questions anytime.\n"
        "5. **Overview** shows the chart at a glance (and you can edit patient details there), and "
        "**Measures & Trends** turns standardized measures into tables and charts.\n"
    )
    st.info("This pilot uses practice and synthetic data only. Please don't enter real patient information.")
    st.write("**Add your first patient on the left to begin.**")
    st.stop()

if "_goto_view" in st.session_state:
    st.session_state.view = st.session_state.pop("_goto_view")

view = st.radio("Workspace", VIEWS, horizontal=True, key="view", label_visibility="collapsed")
st.divider()

if view == V_OVERVIEW:
    render_executive(case)
elif view == V_INTAKE:
    render_intake(case)
elif view == V_MEASURES:
    render_graphical(case)
elif view == V_EVIDENCE:
    render_literature(case)
