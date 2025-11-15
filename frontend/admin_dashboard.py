# frontend/admin_dashboard.py
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import requests

def colored_badge(text, color):
    return f"""
    <span style="
        background-color:{color};
        color:white;
        padding:4px 10px;
        border-radius:5px;
        font-size:0.9rem;
        font-weight:600;">
        {text.upper()}
    </span>
    """

RISK_COLORS = {
    "low": "#2ecc71",
    "medium": "#f1c40f",
    "high": "#e74c3c"
}

CONSENT_COLORS = {
    True: "#2ecc71",
    False: "#e74c3c"
}

BACKEND_URL = "http://127.0.0.1:8000"

# Auto-refresh dashboard
st.set_page_config(page_title="HopeChain Admin Dashboard", layout="wide")
st_autorefresh(interval=5000, key="dashboard_refresh")

st.title("🌍 HopeChain — Admin Dashboard")
st.write("Monitor cases, verify consent, assign counsellors, manage risk and status.")

# -------------------- LOAD CASES --------------------
def load_cases():
    try:
        resp = requests.get(f"{BACKEND_URL}/cases", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("cases", [])
        return []
    except Exception as e:
        st.error(f"Error loading cases: {e}")
        return []

cases = load_cases()

# -------------------- STAT COUNTERS --------------------
all_cases = cases

new_count = sum(1 for c in all_cases if c["status"] == "new")
assigned_count = sum(1 for c in all_cases if c["status"] == "assigned")
high_risk_count = sum(1 for c in all_cases if c["risk"]["risk_level"] == "high" or c["risk"]["should_escalate"])
resolved_count = sum(1 for c in all_cases if c["status"] == "resolved")
no_consent_count = sum(1 for c in all_cases if c.get("consent") is False)

colA, colB, colC, colD, colE = st.columns(5)
colA.metric("🟦 New", new_count)
colB.metric("🟨 Assigned", assigned_count)
colC.metric("🔴 High-Risk", high_risk_count)
colD.metric("🟩 Resolved", resolved_count)
colE.metric("⚠️ Missing Consent", no_consent_count)

# -------------------- SIDEBAR FILTERS --------------------
st.sidebar.header("Filters")

selected_status = st.sidebar.selectbox(
    "Filter by case status",
    ["all", "new", "assigned", "in_progress", "resolved"]
)

consent_filter = st.sidebar.selectbox(
    "Filter by consent",
    ["all", "consent_given", "no_consent"]
)

# Apply filters
if selected_status != "all":
    cases = [c for c in cases if c.get("status") == selected_status]

if consent_filter == "consent_given":
    cases = [c for c in cases if c.get("consent") is True]
elif consent_filter == "no_consent":
    cases = [c for c in cases if c.get("consent") is False]

# -------------------- DISPLAY CASES --------------------
if not cases:
    st.info("No cases to show.")
else:
    for case in cases:
        st.markdown("---")
        col1, col2 = st.columns([2, 1])   # ← THIS WAS MISSING IN YOUR FILE

        # ============ LEFT COLUMN (info) ===============
        with col1:
            st.subheader(f"🆔 Case: {case.get('intake_id')}")
            st.write(f"**Status:** `{case.get('status')}`")

            # Consent badge
            consent = case.get("consent", False)
            st.markdown(
                f"Consent: {colored_badge(str(consent), CONSENT_COLORS.get(consent))}",
                unsafe_allow_html=True
            )

            # Emotion
            st.write(f"**Emotion:** `{case['emotion']['emotion']}` ({case['emotion']['category']})")

            # Risk badge
            risk_level = case["risk"]["risk_level"]
            risk_color = RISK_COLORS.get(risk_level, "#95a5a6")
            st.markdown(
                f"Risk: {colored_badge(risk_level, risk_color)} "
                f"&nbsp;&nbsp; Score: **{case['risk']['risk_score']}**",
                unsafe_allow_html=True
            )

            # Needs
            st.write(f"**Needs:** {', '.join(case['needs']['needs'])}")

            # Danger alert
            if risk_level == "high":
                st.error("🚨 High-risk case: Immediate attention needed!")

            st.write("### Safe Text")
            st.code(case['safety']['safe_text'])

        # ============ RIGHT COLUMN (actions) ===============
        with col2:
            st.write("### Actions")

            # Assign case
            assignee = st.text_input(
                f"Assign to (Case {case['intake_id']})",
                key=f"assign_{case['intake_id']}"
            )
            if st.button("Assign", key=f"btn_assign_{case['intake_id']}"):
                requests.post(
                    f"{BACKEND_URL}/cases/{case['intake_id']}/assign",
                    params={"assignee": assignee}
                )
                st.success("Assigned!")
                st.experimental_rerun()

            # Status change
            new_status = st.selectbox(
                f"Change status (Case {case['intake_id']})",
                ["new", "assigned", "in_progress", "resolved"],
                key=f"status_{case['intake_id']}"
            )
            if st.button("Update Status", key=f"btn_status_{case['intake_id']}"):
                requests.post(
                    f"{BACKEND_URL}/cases/{case['intake_id']}/update_status",
                    params={"new_status": new_status}
                )
                st.success("Status updated!")
                st.experimental_rerun()

            # Resolve
            if st.button("Resolve Case", key=f"btn_resolve_{case['intake_id']}"):
                requests.post(f"{BACKEND_URL}/cases/{case['intake_id']}/resolve")
                st.success("Case resolved!")
                st.experimental_rerun()

            # PDF
            if st.button("Generate PDF (text-only)", key=f"btn_pdf_{case['intake_id']}"):
                try:
                    resp = requests.post(f"{BACKEND_URL}/cases/{case['intake_id']}/pdf", timeout=10)
                    if resp.status_code == 200:
                        st.success("PDF ready. Download below.")
                        st.download_button(
                            label="Download PDF",
                            data=resp.content,
                            file_name=f"hopechain_case_{case['intake_id']}.pdf",
                            mime="application/pdf",
                            key=f"download_pdf_{case['intake_id']}"
                        )
                    else:
                        st.error(f"Failed to generate PDF: {resp.status_code}")
                except Exception as e:
                    st.error(f"Error generating PDF: {e}")

        st.markdown("---")