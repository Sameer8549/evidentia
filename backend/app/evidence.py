from datetime import date, datetime
import hashlib
import re
import uuid
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.ocr import OCRPageResult


class MatchedQuote(BaseModel):
    page_index: int
    char_start: int
    char_end: int
    matched_text: str
    bounding_boxes: List[Dict[str, int]] = Field(default_factory=list)


class EvidenceRecord(BaseModel):
    fact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fact_type: str
    candidate_value: str
    original_quotation: Optional[str] = None
    status: str = "UNVERIFIED"  # SUPPORTED_TEXT, UNVERIFIED, REVIEW_REQUIRED, VERIFICATION_FAILED
    matched_quotes: List[MatchedQuote] = Field(default_factory=list)
    explanation: Optional[str] = None


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    """Case-fold and collapse whitespace while retaining original character offsets."""
    normalized: list[str] = []
    offsets: list[int] = []
    in_whitespace = False

    for index, char in enumerate(text):
        if char.isspace():
            if normalized and not in_whitespace:
                normalized.append(" ")
                offsets.append(index)
            in_whitespace = True
            continue

        folded = char.casefold()
        for folded_char in folded:
            normalized.append(folded_char)
            offsets.append(index)
        in_whitespace = False

    while normalized and normalized[-1] == " ":
        normalized.pop()
        offsets.pop()

    return "".join(normalized), offsets


def normalize_text(text: str) -> str:
    """Normalize case and whitespace for quotation comparison."""
    return _normalized_with_offsets(text)[0].strip()


def match_claim_to_evidence(
    candidate_value: str,
    quotation: Optional[str],
    fact_type: str,
    ocr_pages: List[OCRPageResult],
) -> EvidenceRecord:
    record = EvidenceRecord(
        fact_type=fact_type,
        candidate_value=candidate_value,
        original_quotation=quotation,
    )

    if not quotation:
        record.status = "UNVERIFIED"
        record.explanation = "No candidate quotation provided by model."
        return record

    normalized_quote, _ = _normalized_with_offsets(quotation)
    if not normalized_quote:
        record.status = "UNVERIFIED"
        record.explanation = "Candidate quotation is empty after normalization."
        return record

    for page in ocr_pages:
        normalized_page, offsets = _normalized_with_offsets(page.text)
        search_from = 0

        while True:
            normalized_start = normalized_page.find(normalized_quote, search_from)
            if normalized_start < 0:
                break
            normalized_end = normalized_start + len(normalized_quote)
            # Map normalized indices back into the exact unmodified OCR text.
            start_idx = offsets[normalized_start]
            end_idx = offsets[normalized_end - 1] + 1
            boxes = [
                {
                    "x": word.x,
                    "y": word.y,
                    "width": word.width,
                    "height": word.height,
                }
                for word in page.words
                if word.char_end > start_idx and word.char_start < end_idx
            ]
            record.matched_quotes.append(
                MatchedQuote(
                    page_index=page.page_index,
                    char_start=start_idx,
                    char_end=end_idx,
                    matched_text=page.text[start_idx:end_idx],
                    bounding_boxes=boxes,
                )
            )
            search_from = normalized_end

    if record.matched_quotes:
        record.status = "SUPPORTED_TEXT"
        record.explanation = (
            "Candidate quotation was located in OCR text. This confirms text occurrence, "
            "not semantic correctness or document authenticity."
        )
    else:
        record.status = "VERIFICATION_FAILED"
        record.explanation = "Candidate quotation was not found in OCR text."

    return record


class DeterministicCheck(BaseModel):
    check_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    check_type: str
    evidence_used: List[str] = Field(default_factory=list)
    expected_value: Optional[str] = None
    observed_value: Optional[str] = None
    outcome: str = "NOT_RUN"  # PASS, FAIL, INCONCLUSIVE, NOT_RUN
    explanation: Optional[str] = None
    is_applicable: bool = True


_DATE_PATTERNS = (
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


def _extract_dates(value: str) -> list[date]:
    candidates = [value]
    candidates.extend(re.findall(r"\b\d{1,2}[ /-][A-Za-z]{3,9}[, ]+\d{4}\b", value))
    candidates.extend(re.findall(r"\b[A-Za-z]{3,9}[ ]+\d{1,2},?[ ]+\d{4}\b", value))
    candidates.extend(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", value))
    candidates.extend(re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", value))

    parsed: set[date] = set()
    for candidate in candidates:
        candidate = re.sub(r"\s+", " ", candidate.strip())
        for pattern in _DATE_PATTERNS:
            try:
                parsed.add(datetime.strptime(candidate, pattern).date())
                break
            except ValueError:
                continue
    return sorted(parsed)


def _extract_amounts(value: str) -> list[str]:
    matches = re.findall(
        r"(?:₹|INR|Rs\.?|\$|USD|EUR|€|£)?\s*\d[\d,]*(?:\.\d{1,2})?",
        value,
        flags=re.IGNORECASE,
    )
    results = []
    for match in matches:
        digits = re.sub(r"[^\d.]", "", match)
        if digits:
            try:
                results.append(f"{float(digits):.2f}")
            except ValueError:
                pass
    return results


def run_deterministic_checks(
    evidence_records: List[EvidenceRecord],
) -> List[DeterministicCheck]:
    checks: list[DeterministicCheck] = []

    for record in evidence_records:
        if record.status != "SUPPORTED_TEXT":
            continue

        if record.fact_type == "dates_and_deadlines":
            candidate_dates = _extract_dates(record.candidate_value)
            quote_dates = _extract_dates(record.original_quotation or "")
            check = DeterministicCheck(
                check_type="date_validation",
                evidence_used=[record.fact_id],
                expected_value=record.candidate_value,
                observed_value=record.original_quotation,
            )
            if candidate_dates and quote_dates:
                check.outcome = "PASS" if set(candidate_dates) <= set(quote_dates) else "FAIL"
                check.explanation = (
                    "Parsed candidate date agrees with quotation."
                    if check.outcome == "PASS"
                    else "Parsed candidate date conflicts with quotation."
                )
            else:
                check.outcome = "INCONCLUSIVE"
                check.explanation = "Could not unambiguously parse both candidate and quoted dates."
            checks.append(check)

        elif record.fact_type == "fees_and_amounts":
            candidate_amounts = _extract_amounts(record.candidate_value)
            quote_amounts = _extract_amounts(record.original_quotation or "")
            check = DeterministicCheck(
                check_type="amount_validation",
                evidence_used=[record.fact_id],
                expected_value=record.candidate_value,
                observed_value=record.original_quotation,
            )
            if candidate_amounts and quote_amounts:
                check.outcome = "PASS" if set(candidate_amounts) <= set(quote_amounts) else "FAIL"
                check.explanation = (
                    "Parsed candidate amount agrees with quotation."
                    if check.outcome == "PASS"
                    else "Parsed candidate amount conflicts with quotation."
                )
            else:
                check.outcome = "INCONCLUSIVE"
                check.explanation = "Could not unambiguously parse both candidate and quoted amounts."
            checks.append(check)

    return checks
