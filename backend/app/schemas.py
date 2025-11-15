# backend/app/schemas.py
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


# ---------------------------------------------------------
# INTAKE MODEL (now includes consent fields)
# ---------------------------------------------------------
class Intake(BaseModel):
    id: str
    text: str
    lang: str = "en"
    source: str = "text"   # "audio" or "text"

    # NEW — Explicit child/guardian consent
    consent: bool = False                 # user must agree
    consent_type: Optional[str] = None    # "self", "guardian"
    store_raw: bool = False               # whether raw text can be saved


# ---------------------------------------------------------
# SAFETY BLOCK
# ---------------------------------------------------------
class SafetyResult(BaseModel):
    safe_text: str
    pii_removed: bool
    safety_flags: List[str] = []
    escalation_required: bool = False
    redacted_fields: List[str] = []   # which PII fields were removed


# ---------------------------------------------------------
# NEEDS ASSESSOR
# ---------------------------------------------------------
class NeedsResult(BaseModel):
    needs: List[str]
    urgency: str
    confidence: float


# ---------------------------------------------------------
# CURATED OUTPUT
# (we keep pdf_url/audio_url even if unused now — future proof)
# ---------------------------------------------------------
class CuratedOutput(BaseModel):
    microstory: str
    illustration_prompts: List[str] = []
    pdf_url: Optional[str] = None
    audio_url: Optional[str] = None


# ---------------------------------------------------------
# EMOTION BLOCK
# ---------------------------------------------------------
class EmotionResult(BaseModel):
    emotion: str
    intensity: float
    category: str
    support_suggestion: str
    matched_phrases: List[str] = []


# ---------------------------------------------------------
# RISK SCORING BLOCK
# ---------------------------------------------------------
class RiskResult(BaseModel):
    risk_score: float
    risk_level: str
    should_escalate: bool
    recommended_action: str
    reason: Optional[str] = None
    matched_phrases: List[str] = []


# ---------------------------------------------------------
# MAIN RESPONSE OBJECT
# ---------------------------------------------------------
class IntakeResponse(BaseModel):
    intake_id: str
    safety: SafetyResult
    curated: CuratedOutput
    needs: NeedsResult
    emotion: EmotionResult
    risk: RiskResult