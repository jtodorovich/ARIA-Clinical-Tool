import streamlit as st
from intake import parse_clinician_note
from rag import retrieve_literature

st.title("ARIA")
st.subheader("Adaptive Rehabilitation Intelligence Assistant")

st.write("This is the starting point for ARIA's clinician interface.")

clinician_note = st.text_area("Enter a clinician note or query:")

if st.button("Submit"):
    if clinician_note:
        with st.spinner("Analyzing note..."):
            parsed = parse_clinician_note(clinician_note)

        st.write("Structured output:")
        st.json(parsed)

        with st.spinner("Searching medical literature..."):
            literature = retrieve_literature(parsed)

        st.write(f"Search query used: `{literature['query_used']}`")
        st.write("Relevant literature:")
        for source in literature["sources"]:
            with st.expander(f"{source['title']} (PMID: {source['pmid']})"):
                st.write(source["abstract"])
    else:
        st.warning("Please enter some text before submitting.")
