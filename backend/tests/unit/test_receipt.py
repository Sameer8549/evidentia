from app.receipt import EvidenceReceipt, ReceiptMetadata, ReceiptProcessing
from app.evidence import EvidenceRecord


def test_evidence_receipt():
    metadata = ReceiptMetadata(
        receipt_id="r-123",
        ingestion_id="i-123",
        source_sha256="abc123sha",
        filename="test.pdf",
        file_type="application/pdf",
        page_count=1,
    )
    processing = ReceiptProcessing(model_tag="gemma4:e4b")

    receipt = EvidenceReceipt(
        metadata=metadata,
        processing=processing,
        global_status="COMPLETED",
        extracted_facts=[
            EvidenceRecord(
                fact_type="dates_and_deadlines", candidate_value="18 October 2026"
            )
        ],
    )

    data = receipt.model_dump(mode="json")
    assert data["schema_version"] == "1.0.0"
    assert data["metadata"]["source_sha256"] == "abc123sha"

    digest = receipt.generate_digest()
    assert isinstance(digest, str)
    assert len(digest) == 64  # SHA-256 length
