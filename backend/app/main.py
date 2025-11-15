import os
print(">>> FASTAPI LOADING FROM:", os.path.abspath(__file__))

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse

import re
import math
import io
from typing import Dict, List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

import subprocess
import json
from datetime import datetime

from .schemas import (
    Intake,
    SafetyResult,
    CuratedOutput,
    IntakeResponse,
    NeedsResult,
    EmotionResult,
    RiskResult
)

# -------------------------------------------------------------
# FASTAPI + CASE STORE
# -------------------------------------------------------------
app = FastAPI(title="HopeChain Backend - Intake Demo (with Consent)")
CASE_STORE = []

# -------------------------------------------------------------
# COMMON NAMES FOR REDACTION
# -------------------------------------------------------------
COMMON_FIRST_NAMES = {
    "aaron","abdul","abigail","aditi","adrian","ahmed","aina","akiko","alex","alice","alisha",
    "aliya","allan","amal","amara","aman","amber","amina","amir","amy","andrea","andrew","anita","ankur",
    "anna","anushka","arjun","arthur","ashley","ashwin","ben","benjamin","bianca","brandon","brian","bruno",
    "carlos","carla","charles","chloe","christian","clara","daniel","diego","divya","dmitri","edward","elena",
    "eli","elias","emily","emma","eric","erika","eva","felix","fernando","fiona","gabriel","george","grace",
    "harish","harry","hector","henry","isha","ivan","jack","jacob","james","jane","jasmine","jay","jean",
    "jessica","john","jordan","jose","joseph","josh","joy","juan","julia","justin","karen","karim","katie",
    "kevin","krishna","laura","leo","liam","lina","linda","lisa","lucas","luis","luna","maria","marie","mark",
    "marta","michael","mina","mira","mohammed","monica","nadia","nina","noah","omar","oscar","paul","peter",
    "priya","raj","rakesh","ram","ravi","rebecca","rita","robert","rohit","rosa","roy","ryan","sachin","sara",
    "sarah","sam","samantha","samir","sanjay","sean","selena","shaun","shiva","shivani","shreya","simon",
    "sofia","sunita","suraj","susan","tarun","tina","uma","vanessa","vikas","william","yasmin","yusuf","zara"
}

# -------------------------------------------------------------
# ROOT ENDPOINT
# -------------------------------------------------------------
@app.get("/")
async def root():
    return {"message": "Hello from HopeChain — backend running!"}

# -------------------------------------------------------------
# ANONYMIZER
# -------------------------------------------------------------
def improved_anonymize(text: str):
    original = text
    redacted_fields = set()

    text, n = re.subn(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", "[REDACTED_EMAIL]", text)
    if n: redacted_fields.add("email")

    text, n = re.subn(r"(\+?\d[\d\-\s\(\)]{6,}\d)", "[REDACTED_PHONE]", text)
    if n: redacted_fields.add("phone")

    text, n = re.subn(r"\b\d{4,}\b", "[REDACTED]", text)
    if n: redacted_fields.add("id_number")

    text, n = re.subn(
        r"(address|location)\s*:\s*[^\n]+",
        r"\1: [REDACTED]",
        text,
        flags=re.IGNORECASE
    )
    if n: redacted_fields.add("address")

    text, n = re.subn(
        r"\b(my name is|i am|i'm|this is)\s+[A-Z][A-Za-z\-']{1,20}\b",
        r"\1 [REDACTED_NAME]",
        text,
        flags=re.IGNORECASE
    )
    if n: redacted_fields.add("name")

    def name_filter(m):
        tok = m.group(0)
        if tok.lower() in COMMON_FIRST_NAMES:
            redacted_fields.add("name")
            return "[REDACTED_NAME]"
        return tok

    text = re.sub(r"\b[A-Z][A-Za-z\-']{1,20}\b", name_filter, text)

    text, n = re.subn(r"@\w{3,}", "[REDACTED_HANDLE]", text)
    if n: redacted_fields.add("social_handle")

    return text.strip(), text != original, sorted(list(redacted_fields))

# -------------------------------------------------------------
# NEEDS ASSESSOR
# -------------------------------------------------------------
def simple_needs_assessor(text: str):
    t = text.lower()
    needs = []
    urgency = "low"
    confidence = 0.6

    if any(w in t for w in ["hungry", "food", "starving", "hunger"]):
        needs.append("food")
    if any(w in t for w in ["sick", "hospital", "hurt", "injured", "medicine"]):
        needs.append("medical")
    if any(w in t for w in ["school", "teacher", "study", "homework"]):
        needs.append("education")
    if any(w in t for w in ["home", "house", "shelter", "camp"]):
        needs.append("shelter")
    if any(w in t for w in ["scared", "threat", "abuse", "afraid", "traffick"]):
        needs.append("safety")
        urgency = "high"
        confidence = 0.9

    if not needs:
        needs = ["none"]

    return needs, urgency, confidence

# -------------------------------------------------------------
# EMOTION LEXICONS
# -------------------------------------------------------------
EMOTION_LEXICON = {
    "sad": ("sadness",1.0),"sadness":("sadness",1.0),"lonely":("sadness",1.0),
    "miss":("sadness",0.6),"cry":("sadness",0.9),"tears":("sadness",0.9),
    "alone":("sadness",1.0),"hurt":("sadness",0.8),
    "scared":("fear",1.0),"afraid":("fear",1.0),"frightened":("fear",1.0),
    "danger":("fear",1.0),"unsafe":("fear",0.9),
    "angry":("anger",1.0),"mad":("anger",0.9),"upset":("anger",0.6),
    "hope":("hope",1.0),"dream":("hope",0.8),
    "thank":("relief",0.7),"grateful":("relief",0.9),"safe":("relief",0.8),
    "suicide":("despair",1.5),"kill":("despair",1.2),
    "death":("despair",1.0),"hopeless":("despair",1.0),
}

EMOTION_PHRASES = [
    "i want to die","kill myself","end my life",
    "i can't go on","no hope","give up","nobody cares"
]

# -------------------------------------------------------------
# EMOTION ANALYSIS
# -------------------------------------------------------------
def analyze_emotion(text: str) -> Dict:
    if not text.strip():
        return {
            "emotion":"neutral",
            "intensity":0.0,
            "category":"low",
            "support":"encouragement",
            "matched_phrases":[]
        }

    t = text.lower()
    tokens = re.findall(r"\b[\w']+\b", t)
    scores = {}
    matched = []

    for phrase in EMOTION_PHRASES:
        if phrase in t:
            matched.append(phrase)
            scores["despair"] = scores.get("despair",0)+1.8

    for tok in tokens:
        if tok in EMOTION_LEXICON:
            label, weight = EMOTION_LEXICON[tok]
            scores[label] = scores.get(label,0)+weight

    if not scores:
        return {
            "emotion":"neutral",
            "intensity":0.15,
            "category":"low",
            "support":"encouragement",
            "matched_phrases":[]
        }

    dominant, raw = max(scores.items(), key=lambda x:x[1])
    intensity = float(round(math.tanh(raw/3.0), 3))

    if intensity >= 0.8: category = "high"
    elif intensity >= 0.35: category = "medium"
    else: category = "low"

    # Support suggestion
    support = "encouragement"
    if dominant in ("fear","despair") or category == "high":
        support = "counselling"
    elif dominant == "sadness" and category != "low":
        support = "counselling"
    elif dominant == "relief":
        support = "peer_support"

    return {
        "emotion":dominant,
        "intensity":intensity,
        "category":category,
        "support":support,
        "matched_phrases":matched
    }

def simple_needs_assessor(text: str):
    t=text.lower()
    needs=[]
    urgency="low"
    confidence=0.6

    if any(w in t for w in ["hungry","food","starving","hunger"]):
        needs.append("food")
    if any(w in t for w in ["sick","hospital","hurt","injured","medicine"]):
        needs.append("medical")
    if any(w in t for w in ["school","teacher","study","homework"]):
        needs.append("education")
    if any(w in t for w in ["home","house","shelter","camp"]):
        needs.append("shelter")
    if any(w in t for w in ["scared","threat","abuse","afraid","traffick"]):
        needs.append("safety")
        urgency="high"; confidence=0.9

    if not needs:
        needs=["none"]

    return needs, urgency, confidence


EMOTION_LEXICON = {
    "sad":("sadness",1.0), "sadness":("sadness",1.0), "lonely":("sadness",1.0),
    "miss":("sadness",0.6), "cry":("sadness",0.9), "tears":("sadness",0.9),
    "alone":("sadness",1.0), "hurt":("sadness",0.8),

    "scared":("fear",1.0), "afraid":("fear",1.0), "frightened":("fear",1.0),
    "danger":("fear",1.0), "unsafe":("fear",0.9),

    "angry":("anger",1.0), "mad":("anger",0.9), "upset":("anger",0.6),

    "hope":("hope",1.0), "dream":("hope",0.8),

    "thank":("relief",0.7), "grateful":("relief",0.9), "safe":("relief",0.8),

    "suicide":("despair",1.5), "kill":("despair",1.2),
    "death":("despair",1.0), "hopeless":("despair",1.0),
}

EMOTION_PHRASES = [
    "i want to die", "kill myself", "end my life", "i can't go on",
    "no hope", "give up", "nobody cares",
]


def analyze_emotion(text:str)->Dict:
    if not text.strip():
        return {
            "emotion":"neutral",
            "intensity":0.0,
            "category":"low",
            "support":"encouragement",
            "matched_phrases":[]
        }

    t=text.lower()
    tokens=re.findall(r"\b[\w']+\b", t)
    scores={}; matched=[]

    for p in EMOTION_PHRASES:
        if p in t:
            matched.append(p)
            scores["despair"] = scores.get("despair",0) + 1.8

    for tok in tokens:
        if tok in EMOTION_LEXICON:
            lbl, w = EMOTION_LEXICON[tok]
            scores[lbl] = scores.get(lbl,0) + w

    if not scores:
        return {
            "emotion":"neutral",
            "intensity":0.15,
            "category":"low",
            "support":"encouragement",
            "matched_phrases":[]
        }

    dominant, raw = max(scores.items(), key=lambda x:x[1])
    intensity = float(round(math.tanh(raw/3.0), 3))

    if intensity >= 0.8: cat="high"
    elif intensity >= 0.35: cat="medium"
    else: cat="low"

    support="encouragement"
    if dominant in ("fear","despair") or cat=="high":
        support="counselling"
    elif dominant=="sadness" and cat!="low":
        support="counselling"
    elif dominant=="relief":
        support="peer_support"

    return {
        "emotion": dominant,
        "intensity": intensity,
        "category": cat,
        "support": support,
        "matched_phrases": matched
    }

def compute_risk_score(emotion_info, safety_flags, matched_phrases, needs):
    """
    Improved high-risk detection with clearer thresholds and rationale.
    """

    # ---------------------------------------------------------
    # 1. Absolute high-risk triggers (immediate escalation)
    # ---------------------------------------------------------
    explicit_danger_terms = ["suicide", "kill myself", "end my life",
                             "rape", "traffick", "sell me", "hurt me badly"]

    text_joined = " ".join(matched_phrases).lower()

    if any(term in text_joined for term in explicit_danger_terms):
        return {
            "risk_score": 1.0,
            "risk_level": "high",
            "should_escalate": True,
            "recommended_action": "urgent_human_review_assign_counsellor",
            "reason": "explicit_immediate_danger",
            "matched_phrases": matched_phrases
        }

    # If safety_flags contain danger keywords
    if any(flag for flag in safety_flags):
        return {
            "risk_score": 0.95,
            "risk_level": "high",
            "should_escalate": True,
            "recommended_action": "urgent_human_review_assign_counsellor",
            "reason": "safety_flag_triggered",
            "matched_phrases": matched_phrases
        }

    # ---------------------------------------------------------
    # 2. Weighted emotional scoring
    # ---------------------------------------------------------
    weights = {
        "despair": 0.65,
        "fear": 0.45,
        "sadness": 0.25,
        "anger": 0.20
    }

    risk = 0.0
    reasons = []

    dom = emotion_info["emotion"]
    intensity = emotion_info["intensity"]

    if dom in weights:
        risk += weights[dom]
        reasons.append(f"emotion={dom}")

    # increase risk based on intensity
    risk += intensity * 0.55

    # ---------------------------------------------------------
    # 3. Boost for matched phrases (strong emotional markers)
    # ---------------------------------------------------------
    risk += len(matched_phrases) * 0.25

    # ---------------------------------------------------------
    # 4. Needs-based risk signals
    # ---------------------------------------------------------
    if "safety" in needs:
        risk += 0.25
        reasons.append("need=safety")

    if "medical" in needs:
        risk += 0.15
        reasons.append("need=medical")

    # ---------------------------------------------------------
    # 5. Clamp score between 0–1
    # ---------------------------------------------------------
    risk = min(1.0, max(0.0, risk))

    # ---------------------------------------------------------
    # 6. Risk Levels
    # ---------------------------------------------------------
    if risk >= 0.7:
        level = "high"
        should_escalate = True
    elif risk >= 0.35:
        level = "medium"
        should_escalate = False
    else:
        level = "low"
        should_escalate = False

    # ---------------------------------------------------------
    # 7. Recommended action
    # ---------------------------------------------------------
    if level == "high":
        action = "assign_to_counsellor (urgent)"
    elif "medical" in needs:
        action = "assign_to_medical_NGO"
    elif "education" in needs:
        action = "assign_to_education_NGO"
    elif "shelter" in needs:
        action = "assign_to_shelter_NGO"
    else:
        action = "monitor_or_volunteer_followup"

    # ---------------------------------------------------------
    # 8. Final return
    # ---------------------------------------------------------
    return {
        "risk_score": round(risk, 3),
        "risk_level": level,
        "should_escalate": should_escalate,
        "recommended_action": action,
        "reason": ";".join(reasons),
        "matched_phrases": matched_phrases
    }

def microstory_from_text(safe_text):
    sentences = re.split(r'(?<=[.!?])\s+', safe_text)
    base = " ".join(sentences[:2]).strip()
    if len(base) < 10:
        base = safe_text

    story = base + " They hold onto hope and dream of a kinder tomorrow."
    prompts = [
        "A gentle, storybook-style illustration of a child holding a small toy",
        "A soft watercolor sunrise behind a humble home"
    ]
    return story, prompts

def generate_microstory_llm(safe_text):
    prompt = (
        "Rewrite this as a short, warm microstory (2-3 sentences). "
        "Do NOT invent details. Keep [REDACTED_NAME] untouched.\n\n"
        f"TEXT: {safe_text}"
    )

    try:
        r = subprocess.run(
            ["ollama", "run", "phi3.5"],
            input=prompt.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20
        )
        out = r.stdout.decode().strip()
        if len(out) > 10:
            return out
    except:
        pass

    # fallback
    return microstory_from_text(safe_text)[0]

def draw_wrapped_text(c, text, x, y, maxw, leading=12):
    words = text.split()
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, "Helvetica", 10) <= maxw:
            line = test
        else:
            c.drawString(x, y, line)
            y -= leading
            line = w
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def generate_case_pdf_bytes(case):
    buf = io.BytesIO()
    pw, ph = A4
    c = canvas.Canvas(buf, pagesize=A4)

    left = 20 * mm
    y = ph - 20 * mm
    w = pw - 40 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, "HopeChain — Case Report")
    y -= 15

    c.setFont("Helvetica", 10)
    c.drawString(left, y, f"Case ID: {case.get('intake_id')}")
    y -= 12
    c.drawString(left, y, f"Status: {case.get('status')}")
    y -= 12

    risk = case["risk"]
    c.drawString(left, y, f"Risk Level: {risk['risk_level']} (Score {risk['risk_score']})")
    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Microstory:")
    y -= 14
    c.setFont("Helvetica", 10)
    y = draw_wrapped_text(c, case["curated"]["microstory"], left, y, w)

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Safe Text:")
    y -= 14
    c.setFont("Helvetica", 10)
    y = draw_wrapped_text(c, case["safety"]["safe_text"], left, y, w)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()

# -------------------------------------------------------------
# INTAKE ENDPOINT — Consent + Analysis + Case Storage
# -------------------------------------------------------------
@app.post("/intake/text", response_model=IntakeResponse)
async def intake_text(payload: Intake):
    
    # -----------------------------------------
    # 1. Consent enforcement
    # -----------------------------------------
    if not payload.consent:
        raise HTTPException(
            status_code=400,
            detail="Consent is required before intake can be processed."
        )

    if payload.consent_type not in ("self", "guardian"):
        raise HTTPException(
            status_code=400,
            detail="consent_type must be 'self' or 'guardian'."
        )

    # -----------------------------------------
    # 2. Validate text
    # -----------------------------------------
    if not payload.text.strip():
        raise HTTPException(400, "Text content is empty.")

    # -----------------------------------------
    # 3. Anonymize text
    # -----------------------------------------
    safe_text, pii_removed, redacted_fields = improved_anonymize(payload.text)

    # Safety flags
    safety_flags = []
    if any(k in payload.text.lower() for k in ["suicide", "self harm", "kill myself", "traffick", "rape"]):
        safety_flags.append("possible_immediate_danger")

    safety = SafetyResult(
        safe_text=safe_text,
        pii_removed=pii_removed,
        safety_flags=safety_flags,
        escalation_required=bool(safety_flags),
        redacted_fields=redacted_fields
    )

    # -----------------------------------------
    # 4. Emotion analysis
    # -----------------------------------------
    emotion_info = analyze_emotion(safe_text)

    emotion_result = EmotionResult(
        emotion=emotion_info["emotion"],
        intensity=emotion_info["intensity"],
        category=emotion_info["category"],
        support_suggestion=emotion_info["support"],
        matched_phrases=emotion_info["matched_phrases"]
    )

    # -----------------------------------------
    # 5. Needs + Risk
    # -----------------------------------------
    needs, urgency, confidence = simple_needs_assessor(safe_text)

    risk_info = compute_risk_score(
        emotion_info,
        safety_flags,
        emotion_info["matched_phrases"],
        needs
    )

    risk_result = RiskResult(
        risk_score=risk_info["risk_score"],
        risk_level=risk_info["risk_level"],
        should_escalate=risk_info["should_escalate"],
        recommended_action=risk_info["recommended_action"],
        reason=risk_info["reason"],
        matched_phrases=risk_info["matched_phrases"]
    )

    needs_res = NeedsResult(
        needs=needs,
        urgency=urgency,
        confidence=round(confidence, 2)
    )

    # -----------------------------------------
    # 6. Generate microstory
    # -----------------------------------------
    microstory_text = generate_microstory_llm(safe_text)
    _, prompts = microstory_from_text(safe_text)

    curated = CuratedOutput(
        microstory=microstory_text,
        illustration_prompts=prompts
    )

    # -----------------------------------------
    # 7. Build response
    # -----------------------------------------
    response = IntakeResponse(
        intake_id=payload.id,
        safety=safety,
        curated=curated,
        needs=needs_res,
        emotion=emotion_result,
        risk=risk_result
    )

    # -----------------------------------------
    # 8. Save to CASE_STORE
    # -----------------------------------------
    saved_case = response.dict()
    saved_case["status"] = "new"

    # Consent storage
    saved_case["consent"] = payload.consent
    saved_case["consent_type"] = payload.consent_type
    saved_case["consent_timestamp"] = datetime.utcnow().isoformat()

    if payload.store_raw:
        saved_case["raw_text"] = payload.text

    CASE_STORE.append(saved_case)

    return response

print(">>> REGISTERING /cases ENDPOINT")

@app.get("/cases")
async def get_cases():
    """
    Return all saved cases (in-memory demo store).
    """
    return {"cases": CASE_STORE}


def find_case(cid: str):
    """
    Utility to locate a case by intake_id.
    """
    for c in CASE_STORE:
        if c.get("intake_id") == cid:
            return c
    return None


@app.post("/cases/{case_id}/update_status")
async def update_status(case_id: str, new_status: str):
    """
    Change case status (new, assigned, in_progress, resolved).
    """
    c = find_case(case_id)
    if not c:
        raise HTTPException(404, "Case not found")

    c["status"] = new_status
    return {"message": "Status updated", "case": c}


@app.post("/cases/{case_id}/assign")
async def assign_case(case_id: str, assignee: str):
    """
    Assign a case to a volunteer/counsellor.
    """
    c = find_case(case_id)
    if not c:
        raise HTTPException(404, "Case not found")

    c["assigned_to"] = assignee
    c["status"] = "assigned"
    return {"message": "Assigned", "case": c}


@app.post("/cases/{case_id}/resolve")
async def resolve_case(case_id: str):
    """
    Mark case as resolved.
    """
    c = find_case(case_id)
    if not c:
        raise HTTPException(404, "Case not found")

    c["status"] = "resolved"
    return {"message": "Resolved", "case": c}


@app.post("/cases/{case_id}/pdf")
async def case_pdf(case_id: str):
    """
    Generate a text-only PDF with:
    - Case ID
    - Status
    - Risk score
    - Microstory
    - Safe text
    """
    c = find_case(case_id)
    if not c:
        raise HTTPException(404, "Case not found")

    pdf_bytes = generate_case_pdf_bytes(c)
    stream = io.BytesIO(pdf_bytes)
    stream.seek(0)

    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="hopechain_case_{case_id}.pdf"'
        }
    )