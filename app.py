import streamlit as st
from intake import parse_clinician_note
from rag import retrieve_literature
from literacy_engine import generate_response, continue_conversation
from log import log_interaction

st.title("ARIA")
st.subheader("Adaptive Rehabilitation Intelligence Assistant")

if "conversation" not in st.session_state:
    st.session_state.conversation = []
    st.session_state.tier_used = None
    st.session_state.parsed = None
    st.session_state.literature = None
    st.session_state.original_note = None

if not st.session_state.conversation:
    st.write("Enter a clinician note below. ARIA will confirm the diagnosis, pull relevant literature, and respond as a mentor calibrated to your preferred level of detail.")

    clinician_note = st.text_area("Enter a clinician note or query:")

    tier_choice = st.selectbox(
        "Response style:",
        options=["Let ARIA decide", "Tier 1 - Quick confirmation", "Tier 2 - Explore options", "Tier 3 - Deep teaching"],
    )
    tier_map = {
        "Let ARIA decide": None,
        "Tier 1 - Quick confirmation": 1,
        "Tier 2 - Explore options": 2,
        "Tier 3 - Deep teaching": 3,
    }

    if st.button("Submit"):
        if clinician_note:
            with st.spinner("Analyzing note..."):
                parsed = parse_clinician_note(clinician_note)
            with st.spinner("Searching medical literature..."):
                literature = retrieve_literature(parsed)
            with st.spinner("Preparing response..."):
                selected_tier = tier_map[tier_choice]
                result = generate_response(parsed, literature, clinician_note, tier=selected_tier)

            st.session_state.parsed = parsed
            st.session_state.literature = literature
            st.session_state.tier_used = result["tier_used"]
            st.session_state.original_note = clinician_note
            st.session_state.conversation = [
                {"role": "user", "content": clinician_note},
                {"role": "assistant", "content": result["response_text"]},
            ]

            log_interaction({
                "type": "initial_response",
                "note": clinician_note,
                "tier_used": result["tier_used"],
                "tier_rationale": result["tier_rationale"],
                "response": result["response_text"],
            })

            st.rerun()
        else:
            st.warning("Please enter some text before submitting.")

else:
    st.markdown(f"**Response tier:** {st.session_state.tier_used}")
    st.divider()

    for turn in st.session_state.conversation:
        role_label = "You" if turn["role"] == "user" else "ARIA"
        with st.chat_message("user" if turn["role"] == "user" else "assistant"):
            st.markdown(f"**{role_label}:** {turn['content']}")

    with st.expander("See extracted clinical data"):
        st.json(st.session_state.parsed)

    with st.expander(f"See {len(st.session_state.literature['sources'])} supporting literature sources"):
        st.write(f"Search query used: `{st.session_state.literature['query_used']}`")
        for source in st.session_state.literature["sources"]:
            st.markdown(f"**{source['title']}** (PMID: {source['pmid']})")
            st.write(source["abstract"])

    st.divider()
    follow_up = st.text_input("Respond to ARIA, ask a question, or share your thinking:")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Send"):
            if follow_up:
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

    with col2:
        if st.button("Start a new case"):
            st.session_state.conversation = []
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
