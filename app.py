import streamlit as st
from intake import parse_clinician_note

st.title("ARIA")
st.subheader("Adaptive Rehabilitation Intelligence Assistant")

st.write("This is the starting point for ARIA's clinician interface.")

clinician_note = st.text_area("Enter a clinician note or query:")

if st.button("Submit"):
    if clinician_note:
        with st.spinner("Analyzing note..."):
            result = parse_clinician_note(clinician_note)
        st.write("Structured output:")
        st.json(result)
    else:
        st.warning("Please enter some text before submitting.")
