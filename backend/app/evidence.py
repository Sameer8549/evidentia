from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
import re

from app.ocr import OCRPageResult

class MatchedQuote(BaseModel):
    page_index: int
    char_start: int
    char_end: int
    matched_text: str
    bounding_boxes: List[Dict[str, int]] = []
    
class EvidenceRecord(BaseModel):
    fact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fact_type: str
    candidate_value: str
    original_quotation: Optional[str] = None
    status: str = "UNVERIFIED" # SUPPORTED_TEXT, UNVERIFIED, REVIEW_REQUIRED, VERIFICATION_FAILED
    matched_quotes: List[MatchedQuote] = []
    explanation: Optional[str] = None
    
def normalize_text(text: str) -> str:
    """Normalize text by removing extra whitespace and lowering case for robust matching."""
    return re.sub(r'\s+', ' ', text).strip().lower()

def match_claim_to_evidence(candidate_value: str, quotation: Optional[str], fact_type: str, ocr_pages: List[OCRPageResult]) -> EvidenceRecord:
    record = EvidenceRecord(
        fact_type=fact_type,
        candidate_value=candidate_value,
        original_quotation=quotation
    )
    
    if not quotation:
        record.status = "UNVERIFIED"
        record.explanation = "No candidate quotation provided by model."
        return record
        
    normalized_quote = normalize_text(quotation)
    if not normalized_quote:
        record.status = "UNVERIFIED"
        record.explanation = "Candidate quotation is empty after normalization."
        return record

    matched = False
    
    for page in ocr_pages:
        page_text = page.text
        normalized_page_text = normalize_text(page_text)
        
        # simple substring match on normalized text is a bit tricky to map back to original char offsets reliably
        # Let's try exact matching on original text first, then case-insensitive
        
        # Case insensitive find
        lower_page = page_text.lower()
        lower_quote = quotation.lower()
        
        start_idx = lower_page.find(lower_quote)
        if start_idx != -1:
            end_idx = start_idx + len(quotation)
            
            # Map to bounding boxes
            boxes = []
            for word in page.words:
                # If word overlaps with matched text
                if not (word.char_end <= start_idx or word.char_start >= end_idx):
                    boxes.append({
                        "x": word.x,
                        "y": word.y,
                        "width": word.width,
                        "height": word.height
                    })
                    
            record.matched_quotes.append(MatchedQuote(
                page_index=page.page_index,
                char_start=start_idx,
                char_end=end_idx,
                matched_text=page_text[start_idx:end_idx],
                bounding_boxes=boxes
            ))
            matched = True
            
    if matched:
        record.status = "SUPPORTED_TEXT"
        record.explanation = "Quotation found in source document."
    else:
        record.status = "VERIFICATION_FAILED"
        record.explanation = "Quotation not found in OCR text."
        
    return record

class DeterministicCheck(BaseModel):
    check_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    check_type: str # e.g. "date_validation", "amount_match"
    evidence_used: List[str] = [] # list of fact_ids
    expected_value: Optional[str] = None
    observed_value: Optional[str] = None
    outcome: str = "NOT_RUN" # PASS, FAIL, INCONCLUSIVE, NOT_RUN
    explanation: Optional[str] = None
    is_applicable: bool = True

def run_deterministic_checks(evidence_records: List[EvidenceRecord]) -> List[DeterministicCheck]:
    checks = []
    
    for record in evidence_records:
        if record.status != "SUPPORTED_TEXT":
            continue
            
        if record.fact_type == "dates_and_deadlines":
            # Very basic deterministic check: if quotation doesn't match the extracted value semantically
            # A full implementation would parse dates, but we can do a substring check for now
            check = DeterministicCheck(
                check_type="date_validation",
                evidence_used=[record.fact_id],
                expected_value=record.candidate_value,
                observed_value=record.original_quotation
            )
            # If the candidate value is nowhere in the matched quote or vice-versa, it might be a hallucination
            if record.candidate_value.lower() in (record.original_quotation or "").lower() or (record.original_quotation or "").lower() in record.candidate_value.lower():
                check.outcome = "PASS"
                check.explanation = "Extracted date is consistent with quotation."
            else:
                check.outcome = "INCONCLUSIVE"
                check.explanation = "Extracted date may require semantic verification against quotation."
            checks.append(check)
            
    return checks

