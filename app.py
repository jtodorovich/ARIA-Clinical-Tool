import streamlit as st
from intake import parse_clinician_note
from rag import retrieve_literature
from literacy_engine import generate_response

st.title("ARIA")
st.subheader("Adaptive Rehabilitation Intelligence Assistant")

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

        st.divider()
        st.markdown(f"**Response tier used:** {result['tier_used']}  \n*{result['tier_rationale']}*")
        st.markdown(result["response_text"])

        with st.expander("See extracted clinical data"):
            st.json(parsed)

        with st.expander(f"See {len(literature['sources'])} supporting literature sources"):
            st.write(f"Search query used: `{literature['query_used']}`")
            for source in literature["sources"]:
                st.markdown(f"**{source['title']}** (PMID: {source['pmid']})")
                st.write(source["abstract"])
                st.write("")
    else:
        st.warning("Please enter some text before submitting.")
