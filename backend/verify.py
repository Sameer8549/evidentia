import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ALLOWED_CLAIM_STATUSES = {
    "SUPPORTED_TEXT",
    "UNVERIFIED",
    "REVIEW_REQUIRED",
    "VERIFICATION_FAILED",
}
_ALLOWED_CHECK_OUTCOMES = {"PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN"}
_ALLOWED_GLOBAL_STATUSES = {"COMPLETED", "PARTIAL", "FAILED"}


def eprint(*args: Any, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)


def _validate_receipt_structure(receipt: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(receipt, dict):
        return ["receipt JSON root must be an object"]

    schema_version = receipt.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.startswith("1."):
        errors.append(f"unsupported receipt schema version: {schema_version!r}")

    metadata = receipt.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
        metadata = {}
    for key in ("receipt_id", "ingestion_id", "filename", "file_type"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            errors.append(f"metadata.{key} must be a non-empty string")

    source_hash = metadata.get("source_sha256")
    if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash):
        errors.append("metadata.source_sha256 must be a 64-character SHA-256 hex digest")

    processing = receipt.get("processing")
    if not isinstance(processing, dict):
        errors.append("processing must be an object")
    elif not isinstance(processing.get("model_tag"), str) or not processing["model_tag"].strip():
        errors.append("processing.model_tag must be a non-empty string")

    facts = receipt.get("extracted_facts")
    if not isinstance(facts, list):
        errors.append("extracted_facts must be an array")
        facts = []
    fact_ids: set[str] = set()
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            errors.append(f"extracted_facts[{index}] must be an object")
            continue
        fact_id = fact.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id:
            errors.append(f"extracted_facts[{index}].fact_id must be a non-empty string")
        elif fact_id in fact_ids:
            errors.append(f"duplicate fact_id: {fact_id}")
        else:
            fact_ids.add(fact_id)
        if fact.get("status") not in _ALLOWED_CLAIM_STATUSES:
            errors.append(f"extracted_facts[{index}].status is invalid")
        quotes = fact.get("matched_quotes", [])
        if not isinstance(quotes, list):
            errors.append(f"extracted_facts[{index}].matched_quotes must be an array")
            continue
        if fact.get("status") == "SUPPORTED_TEXT" and not quotes:
            errors.append(f"extracted_facts[{index}] is SUPPORTED_TEXT but has no matched quote")
        for quote_index, quote in enumerate(quotes):
            prefix = f"extracted_facts[{index}].matched_quotes[{quote_index}]"
            if not isinstance(quote, dict):
                errors.append(f"{prefix} must be an object")
                continue
            page_index = quote.get("page_index")
            start = quote.get("char_start")
            end = quote.get("char_end")
            matched_text = quote.get("matched_text")
            if not isinstance(page_index, int) or page_index < 0:
                errors.append(f"{prefix}.page_index must be a non-negative integer")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                errors.append(f"{prefix} must contain a valid non-empty character range")
            if not isinstance(matched_text, str) or not matched_text:
                errors.append(f"{prefix}.matched_text must be non-empty")
            elif isinstance(start, int) and isinstance(end, int) and start >= 0 and end > start:
                if len(matched_text) != end - start:
                    errors.append(f"{prefix}.matched_text length does not match its character range")
            boxes = quote.get("bounding_boxes", [])
            if not isinstance(boxes, list):
                errors.append(f"{prefix}.bounding_boxes must be an array")
            else:
                for box_index, box in enumerate(boxes):
                    box_prefix = f"{prefix}.bounding_boxes[{box_index}]"
                    if not isinstance(box, dict) or any(
                        not isinstance(box.get(key), int) or box[key] < 0
                        for key in ("x", "y", "width", "height")
                    ):
                        errors.append(f"{box_prefix} must have non-negative integer x, y, width, height")

    checks = receipt.get("deterministic_checks")
    if not isinstance(checks, list):
        errors.append("deterministic_checks must be an array")
        checks = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"deterministic_checks[{index}] must be an object")
            continue
        if check.get("outcome") not in _ALLOWED_CHECK_OUTCOMES:
            errors.append(f"deterministic_checks[{index}].outcome is invalid")
        evidence_used = check.get("evidence_used", [])
        if not isinstance(evidence_used, list) or any(not isinstance(item, str) for item in evidence_used):
            errors.append(f"deterministic_checks[{index}].evidence_used must be an array of fact IDs")
        elif any(item not in fact_ids for item in evidence_used):
            errors.append(f"deterministic_checks[{index}] references a missing fact ID")

    guidance = receipt.get("actionable_guidance", [])
    if not isinstance(guidance, list):
        errors.append("actionable_guidance must be an array")
    resources = receipt.get("resources", [])
    if not isinstance(resources, list):
        errors.append("resources must be an array")
    global_status = receipt.get("global_status")
    if global_status not in _ALLOWED_GLOBAL_STATUSES:
        errors.append("global_status is invalid")

    digest = receipt.get("receipt_digest")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        errors.append("receipt_digest must be a 64-character SHA-256 hex digest")
    return errors


def verify_receipt(receipt_path: Path, source_path: Path) -> int:
    try:
        with receipt_path.open("r", encoding="utf-8") as receipt_file:
            receipt = json.load(receipt_file)
    except Exception as exc:
        eprint(f"[FAIL] Could not read or parse receipt JSON: {exc}")
        return 1

    structural_errors = _validate_receipt_structure(receipt)
    if structural_errors:
        for error in structural_errors:
            eprint(f"[FAIL] Invalid receipt: {error}")
        return 1

    expected_digest = receipt["receipt_digest"]
    receipt_copy = dict(receipt)
    receipt_copy.pop("receipt_digest", None)
    canonical = json.dumps(receipt_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    actual_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual_digest != expected_digest:
        eprint(
            f"[FAIL] Receipt digest mismatch! Expected {expected_digest}, computed "
            f"{actual_digest}. Receipt was tampered with."
        )
        return 1
    print(f"[PASS] Receipt integrity verified (Digest: {actual_digest}).")

    source_hash = hashlib.sha256()
    try:
        with source_path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                source_hash.update(chunk)
    except Exception as exc:
        eprint(f"[FAIL] Could not read source file {source_path}: {exc}")
        return 1
    actual_source_hash = source_hash.hexdigest()
    expected_source_hash = receipt["metadata"]["source_sha256"].lower()
    if actual_source_hash != expected_source_hash:
        eprint(
            f"[FAIL] Source hash mismatch! Receipt says {expected_source_hash}, source is "
            f"{actual_source_hash}. Source was tampered with."
        )
        return 1
    print(f"[PASS] Source document integrity verified (SHA-256: {actual_source_hash}).")

    checks = receipt["deterministic_checks"]
    failed_checks = [check for check in checks if check.get("outcome") == "FAIL"]
    inconclusive_checks = [
        check for check in checks if check.get("outcome") in {"INCONCLUSIVE", "NOT_RUN"}
    ]
    facts = receipt["extracted_facts"]
    unsupported_facts = [fact for fact in facts if fact.get("status") != "SUPPORTED_TEXT"]
    if failed_checks:
        print(f"[WARN] {len(failed_checks)} deterministic claim check(s) failed.", file=sys.stderr)
    if inconclusive_checks:
        print(f"[WARN] {len(inconclusive_checks)} deterministic claim check(s) were inconclusive or not run.", file=sys.stderr)
    if unsupported_facts:
        print(f"[WARN] {len(unsupported_facts)} fact(s) lack supported text evidence.", file=sys.stderr)

    print(f"[INFO] Receipt global status is {receipt['global_status']}.")
    print("[PASS] Receipt structure, digest, and source-file hash verified offline.")
    print("[NOTE] Integrity verification does not establish semantic correctness of every claim.")
    print("[NOTE] A digest alone does not prove issuer authenticity or provide a digital signature.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone offline Evidence Receipt verifier.")
    parser.add_argument("receipt", type=Path, help="Path to the receipt JSON file.")
    parser.add_argument("--source", type=Path, required=True, help="Path to the original source document.")
    arguments = parser.parse_args()

    if not arguments.receipt.is_file():
        eprint(f"[FAIL] Receipt file not found: {arguments.receipt}")
        sys.exit(1)
    if not arguments.source.is_file():
        eprint(f"[FAIL] Source file not found: {arguments.source}")
        sys.exit(1)
    sys.exit(verify_receipt(arguments.receipt, arguments.source))
