import streamlit as st

st.title("ARIA")
st.subheader("Adaptive Rehabilitation Intelligence Assistant")

st.write("This is the starting point for ARIA's clinician interface.")

clinician_note = st.text_area("Enter a clinician note or query:")

if st.button("Submit"):
    if clinician_note:
        st.write("You entered:")
        st.write(clinician_note)
    else:
        st.warning("Please enter some text before submitting.")
