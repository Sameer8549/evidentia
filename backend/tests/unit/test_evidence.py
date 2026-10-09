import pytest
from app.evidence import match_claim_to_evidence, run_deterministic_checks, EvidenceRecord
from app.ocr import OCRPageResult, OCRWord

def test_match_claim_success():
    ocr_pages = [
        OCRPageResult(
            page_index=0,
            text="This is a test application deadline 18 October 2026 for the document.",
            words=[
                OCRWord(text="18", x=10, y=10, width=20, height=10, confidence=99, char_start=36, char_end=38),
                OCRWord(text="October", x=35, y=10, width=50, height=10, confidence=99, char_start=39, char_end=46),
                OCRWord(text="2026", x=90, y=10, width=30, height=10, confidence=99, char_start=47, char_end=51),
            ],
            width=800,
            height=600
        )
    ]
    
    record = match_claim_to_evidence(
        candidate_value="18 October 2026",
        quotation="18 October 2026",
        fact_type="dates_and_deadlines",
        ocr_pages=ocr_pages
    )
    
    assert record.status == "SUPPORTED_TEXT"
    assert len(record.matched_quotes) == 1
    assert record.matched_quotes[0].char_start == 36
    assert record.matched_quotes[0].char_end == 51
    assert len(record.matched_quotes[0].bounding_boxes) == 3

def test_match_claim_failed():
    ocr_pages = [
        OCRPageResult(
            page_index=0,
            text="This is some other text.",
            words=[],
            width=800,
            height=600
        )
    ]
    
    record = match_claim_to_evidence(
        candidate_value="18 October 2026",
        quotation="18 October 2026",
        fact_type="dates_and_deadlines",
        ocr_pages=ocr_pages
    )
    
    assert record.status == "VERIFICATION_FAILED"

def test_deterministic_checks():
    records = [
        EvidenceRecord(
            fact_type="dates_and_deadlines",
            candidate_value="18 October 2026",
            original_quotation="18 October 2026",
            status="SUPPORTED_TEXT"
        ),
        EvidenceRecord(
            fact_type="dates_and_deadlines",
            candidate_value="19 October 2026",
            original_quotation="18 October 2026",
            status="SUPPORTED_TEXT"
        )
    ]
    
    checks = run_deterministic_checks(records)
    
    assert len(checks) == 2
    assert checks[0].outcome == "PASS"
    assert checks[1].outcome == "INCONCLUSIVE"
