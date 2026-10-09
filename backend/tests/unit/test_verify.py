import hashlib
import json
from pathlib import Path

from app.receipt import EvidenceReceipt, ReceiptMetadata, ReceiptProcessing
from verify import verify_receipt


def make_receipt(source_path: Path) -> EvidenceReceipt:
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    receipt = EvidenceReceipt(
        metadata=ReceiptMetadata(
            receipt_id="receipt-test",
            ingestion_id="ingestion-test",
            source_sha256=source_hash,
            filename="notice.txt",
            file_type="text/plain",
            page_count=1,
        ),
        processing=ReceiptProcessing(model_tag="gemma4:e4b"),
        document_summary="సముదాయ నోటీసు",
        extracted_facts=[],
        deterministic_checks=[],
        actionable_guidance=[],
        resources=[],
        global_status="COMPLETED",
    )
    receipt.receipt_digest = receipt.generate_digest()
    return receipt


def test_verify_receipt_passes_for_valid_receipt_and_unicode(tmp_path: Path, capsys):
    source_path = tmp_path / "source.bin"
    receipt_path = tmp_path / "receipt.json"
    source_path.write_bytes(b"official test fixture")

    receipt = make_receipt(source_path)
    receipt_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")

    assert verify_receipt(receipt_path, source_path) == 0
    output = capsys.readouterr().out
    assert "Receipt integrity verified" in output
    assert "Source document integrity verified" in output


def test_verify_receipt_rejects_source_tampering(tmp_path: Path, capsys):
    source_path = tmp_path / "source.bin"
    receipt_path = tmp_path / "receipt.json"
    source_path.write_bytes(b"original")
    receipt = make_receipt(source_path)
    receipt_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")

    source_path.write_bytes(b"modified")
    assert verify_receipt(receipt_path, source_path) == 1
    assert "Source hash mismatch" in capsys.readouterr().err


def test_verify_receipt_rejects_receipt_tampering(tmp_path: Path, capsys):
    source_path = tmp_path / "source.bin"
    receipt_path = tmp_path / "receipt.json"
    source_path.write_bytes(b"original")
    receipt = make_receipt(source_path)
    data = receipt.model_dump(mode="json")
    data["global_status"] = "FAKE"
    receipt_path.write_text(json.dumps(data), encoding="utf-8")

    assert verify_receipt(receipt_path, source_path) == 1
    assert "Invalid receipt" in capsys.readouterr().err or "Receipt digest mismatch" in capsys.readouterr().err


def test_verify_receipt_rejects_malformed_json_shape(tmp_path: Path, capsys):
    source_path = tmp_path / "source.bin"
    receipt_path = tmp_path / "receipt.json"
    source_path.write_bytes(b"original")
    receipt_path.write_text(json.dumps({"schema_version": "1.0.0", "metadata": []}), encoding="utf-8")

    assert verify_receipt(receipt_path, source_path) == 1
    assert "Invalid receipt" in capsys.readouterr().err
