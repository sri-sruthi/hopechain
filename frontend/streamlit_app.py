import streamlit as st
import requests
import uuid
from datetime import datetime

BACKEND_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="HopeChain — Demo", layout="centered")
st.title("HopeChain — Listening & Helping (Demo)")

st.markdown("""
Enter a short story or testimony (demo synthetic data only).  
This UI sends the text to the backend `/intake/text` endpoint and shows:

- anonymized text  
- redacted PII  
- emotion analysis  
- needs  
- microstory  
- risk score  
- PDF export  
""")

# ---------------------- INPUT FORM ----------------------
with st.form("story_form"):

    user_text = st.text_area(
        "Child's story (sample)",
        height=160,
        placeholder="My name is Asha and we had to leave our home..."
    )

    st.markdown("### Consent (Required)")

    guardian_present = st.checkbox(
        "I am the parent/guardian **OR** an authorized NGO worker", value=False
    )

    consent_to_review = st.checkbox(
        "I consent to this story being reviewed by a trained human counsellor", value=False
    )

    consent_to_store_raw = st.checkbox(
        "I agree to storing the original unredacted text (optional)", value=False
    )

    submit = st.form_submit_button("Send to HopeChain")

# ---------------------- PROCESS SUBMISSION ----------------------
if submit:

    if not user_text.strip():
        st.error("Please enter a short story before sending.")
        st.stop()

    if not guardian_present or not consent_to_review:
        st.error("❗ You must check BOTH required consent checkboxes.")
        st.stop()

    payload = {
        "id": str(uuid.uuid4()),
        "text": user_text.strip(),
        "lang": "en",
        "source": "text",
        "consent": True,
        "consent_type": "guardian" if guardian_present else "self",
        "guardian_present": guardian_present,
        "store_raw": bool(consent_to_store_raw)
    }

    # ---- Send to backend ----
    try:
        with st.spinner("Sending to backend..."):
            resp = requests.post(
                f"{BACKEND_URL}/intake/text",
                json=payload,
                timeout=30
            )

        try:
            data = resp.json()
        except:
            st.error("Backend returned non-JSON response.")
            st.write(resp.text)
            st.stop()

        if resp.status_code != 200:
            st.error(f"Backend error {resp.status_code}: {resp.text}")
            st.stop()

        # ---- SUCCESS RESPONSE ----
        st.success("Received response from HopeChain backend ✅")

        # SAFE TEXT
        st.subheader("Anonymized / Safe Text")
        st.code(data["safety"]["safe_text"])

        # REDACTED ITEMS
        redacted = data["safety"].get("redacted_fields", [])
        if redacted:
            st.subheader("Redacted PII")
            st.write(", ".join(redacted))
        else:
            st.info("No PII was removed.")

        # EMOTION
        st.subheader("Emotion Analysis")
        emo = data["emotion"]
        st.write(f"**Dominant emotion:** {emo['emotion']}")
        st.write(f"**Intensity:** {emo['intensity']} • **Category:** {emo['category']}")
        st.write(f"**Suggested support:** {emo['support_suggestion']}")

        if emo["matched_phrases"]:
            with st.expander("Matched high-signal phrases"):
                for p in emo["matched_phrases"]:
                    st.write(f"- {p}")

        # RISK
        st.subheader("Risk Assessment")
        risk = data["risk"]
        st.metric(
            "Risk Score (0–1)",
            value=risk["risk_score"],
            delta=f"Level: {risk['risk_level'].upper()}"
        )
        st.write(f"**Should escalate:** {risk['should_escalate']}")
        st.write(f"**Recommended action:** {risk['recommended_action']}")

        # RISK REASON
        if risk.get("reason"):
            with st.expander("Reason for risk score"):
                st.write(risk["reason"])

        # NEEDS
        st.subheader("Detected Needs & Urgency")
        needs = data["needs"]
        cols = st.columns(len(needs["needs"]))

        for i, need in enumerate(needs["needs"]):
            cols[i].metric(f"Need #{i+1}", need.capitalize())

        st.write(f"**Urgency:** {needs['urgency']} • **Confidence:** {needs['confidence']}")

        # MICROSTORY
        st.subheader("Microstory")
        st.write(data["curated"]["microstory"])

        # PROMPTS
        st.subheader("Illustration Prompts")
        prompts = data["curated"]["illustration_prompts"]
        if prompts:
            for i, p in enumerate(prompts, 1):
                st.write(f"**Prompt {i}:** {p}")
        else:
            st.write("No prompts generated.")

        # ---------------------- PDF DOWNLOAD ----------------------
        st.subheader("Download PDF Case Report")
        case_id = data["intake_id"]

        try:
            pdf_resp = requests.post(
                f"{BACKEND_URL}/cases/{case_id}/pdf",
                timeout=20
            )

            if pdf_resp.status_code == 200:
                st.download_button(
                    label="📄 Download PDF Report",
                    data=pdf_resp.content,
                    file_name=f"hopechain_case_{case_id}.pdf",
                    mime="application/pdf"
                )
            else:
                st.error(f"PDF generation failed: {pdf_resp.status_code}")

        except Exception as e:
            st.error(f"PDF download error: {e}")

    except Exception as e:
        st.error(f"Error connecting to backend: {e}")