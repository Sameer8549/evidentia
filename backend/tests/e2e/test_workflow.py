import pytest
from httpx import AsyncClient
from PIL import Image, ImageDraw, ImageFont
import json
import subprocess
from pathlib import Path
import os
import sys

from app.config import settings


def is_strict_mode():
    return os.getenv("EVIDENTIA_STRICT_E2E") == "1"


@pytest.mark.asyncio
async def test_full_workflow_e2e(async_client: AsyncClient):
    # 1. Dependency Checks
    try:
        tess_res = subprocess.run(
            [settings.evidentia_tesseract_cmd, "--list-langs"],
            capture_output=True,
            text=True,
        )
        if tess_res.returncode != 0 or "eng" not in tess_res.stdout:
            raise ValueError("Tesseract not properly configured or missing 'eng' data.")
    except Exception as e:
        if is_strict_mode():
            pytest.fail(f"Strict Mode: {e}")
        else:
            pytest.skip(f"Tesseract missing: {e}")

    try:
        from app.ollama_client import OllamaClient

        client = OllamaClient()
        await client.check_health()
    except Exception as e:
        if is_strict_mode():
            pytest.fail(f"Strict Mode: {e}")
        else:
            pytest.skip(f"Ollama missing: {e}")

    # 2. Create synthetic image and PDF
    ingestion_dir = Path(settings.evidentia_data_dir) / "test_e2e_source"
    ingestion_dir.mkdir(parents=True, exist_ok=True)
    img_path = ingestion_dir / "e2e_notice.png"
    pdf_path = ingestion_dir / "e2e_notice.pdf"

    img = Image.new("RGB", (1600, 1200), color="white")
    d = ImageDraw.Draw(img)
    try:
        # Pillow 10.1.0+ supports size in load_default
        font = ImageFont.load_default(size=48)
    except TypeError:
        font = ImageFont.load_default()

    d.text((50, 50), "COMMUNITY NOTICE", fill=(0, 0, 0), font=font)
    d.text(
        (50, 150), "Application deadline: 18 October 2026", fill=(0, 0, 0), font=font
    )
    d.text((50, 250), "Required document: ID proof", fill=(0, 0, 0), font=font)
    img.save(img_path)
    img.save(pdf_path, "PDF", resolution=100.0)

    for file_to_test in [img_path, pdf_path]:
        # 3. Ingest
        with open(file_to_test, "rb") as f:
            mime = "application/pdf" if file_to_test.suffix == ".pdf" else "image/png"
            files = {"file": (file_to_test.name, f, mime)}
            response = await async_client.post("/api/ingest", files=files)

        assert response.status_code == 200
        ingestion_data = response.json()
        ingestion_id = ingestion_data["ingestion_id"]

        # 4. Inspect
        # Synchronous backward-compatible endpoint triggers the whole flow
        response = await async_client.post(
            f"/api/inspect/{ingestion_id}?fetch_resources=true", timeout=600.0
        )
        assert response.status_code == 200, f"Inspect failed: {response.text}"
        receipt_data = response.json()

        assert receipt_data["metadata"]["ingestion_id"] == ingestion_id
        assert receipt_data["global_status"] == "COMPLETED"

        # 5. Assert Extractions
        extracted_facts = receipt_data.get("extracted_facts", [])

        # Find the deadline fact
        deadline_fact = next(
            (f for f in extracted_facts if f["fact_type"] == "dates_and_deadlines"),
            None,
        )
        assert deadline_fact is not None, "Did not extract dates_and_deadlines"
        assert "18 October 2026" in deadline_fact.get(
            "candidate_value", ""
        ) or "18 October 2026" in deadline_fact.get("original_quotation", ""), (
            "Did not extract the correct deadline"
        )
        assert deadline_fact.get("status") == "SUPPORTED_TEXT", (
            f"Deadline quotation was not located in OCR: {deadline_fact}"
        )
        assert deadline_fact.get("matched_quotes"), (
            "Deadline has no source quote locations"
        )
        assert any(
            "18 October 2026" in match.get("matched_text", "")
            for match in deadline_fact["matched_quotes"]
        ), "Matched deadline quote does not contain the expected date"

        # Find the required document fact
        doc_fact = next(
            (f for f in extracted_facts if f["fact_type"] == "required_documents"), None
        )
        assert doc_fact is not None, "Did not extract required_documents"
        assert "ID proof" in doc_fact.get(
            "candidate_value", ""
        ) or "ID proof" in doc_fact.get("original_quotation", ""), (
            "Did not extract the correct required document"
        )
        assert doc_fact.get("status") == "SUPPORTED_TEXT", (
            f"Required-document quotation was not located in OCR: {doc_fact}"
        )
        assert doc_fact.get("matched_quotes"), (
            "Required document has no source quote locations"
        )
        assert any(
            "ID proof" in match.get("matched_text", "")
            for match in doc_fact["matched_quotes"]
        ), "Matched required-document quote does not contain ID proof"

        # Assert each supported quote maps to actual OCR character spans and word boxes.
        for fact in extracted_facts:
            if fact.get("status") == "SUPPORTED_TEXT":
                assert fact.get("original_quotation")
                assert fact.get("matched_quotes")
                for match in fact["matched_quotes"]:
                    start, end = match["char_start"], match["char_end"]
                    assert 0 <= start < end
                    assert len(match["matched_text"]) == end - start
                    assert match["matched_text"]
                    assert match.get("bounding_boxes"), (
                        f"Matched quote lacks OCR word boxes: {match}"
                    )
                    for box in match["bounding_boxes"]:
                        assert all(
                            isinstance(box.get(key), int) and box[key] >= 0
                            for key in ("x", "y", "width", "height")
                        )

        # 6. Verify standalone
        receipt_path = Path(settings.evidentia_data_dir) / ingestion_id / "receipt.json"
        assert receipt_path.exists()

        verify_script = Path(__file__).parent.parent.parent / "verify.py"

        result = subprocess.run(
            [
                sys.executable,
                str(verify_script),
                str(receipt_path),
                "--source",
                str(file_to_test),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "[PASS]" in result.stdout

        # 7. Tamper with source and check verification fails
        with open(file_to_test, "ab") as f:
            f.write(b"tampered")

        result_source_tamper = subprocess.run(
            [
                sys.executable,
                str(verify_script),
                str(receipt_path),
                "--source",
                str(file_to_test),
            ],
            capture_output=True,
            text=True,
        )
        assert result_source_tamper.returncode == 1
        assert "Source hash mismatch" in result_source_tamper.stderr

        # 8. Tamper with receipt and check digest verification fails
        with open(receipt_path, "r", encoding="utf-8") as f:
            tampered_receipt = json.load(f)

        tampered_receipt["document_summary"] = "TAMPERED SUMMARY"

        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(tampered_receipt, f)

        result_receipt_tamper = subprocess.run(
            [
                # Re-use the original source path which doesn't matter since digest fails first
                sys.executable,
                str(verify_script),
                str(receipt_path),
                "--source",
                str(file_to_test),
            ],
            capture_output=True,
            text=True,
        )

        assert result_receipt_tamper.returncode == 1
        assert "Receipt digest mismatch" in result_receipt_tamper.stderr
