import sys
import json
import argparse
import hashlib
from pathlib import Path

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def verify_receipt(receipt_path: Path, source_path: Path) -> int:
    try:
        with open(receipt_path, 'r', encoding='utf-8') as f:
            receipt = json.load(f)
    except Exception as e:
        eprint(f"[FAIL] Could not read or parse receipt JSON: {e}")
        return 1

    schema_version = receipt.get("schema_version")
    if not schema_version or not schema_version.startswith("1."):
        eprint(f"[FAIL] Unsupported receipt schema version: {schema_version}")
        return 1
        
    metadata = receipt.get("metadata", {})
    expected_hash = metadata.get("source_sha256")
    
    if not expected_hash:
        eprint("[FAIL] Receipt metadata does not contain a source_sha256 hash.")
        return 1
        
    try:
        sha256_hash = hashlib.sha256()
        with open(source_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        actual_hash = sha256_hash.hexdigest()
    except Exception as e:
        eprint(f"[FAIL] Could not read source file {source_path}: {e}")
        return 1
        
    if actual_hash != expected_hash:
        eprint(f"[FAIL] Hash mismatch! Receipt says {expected_hash}, source is {actual_hash}.")
        return 1
        
    print(f"[PASS] Source document integrity verified (SHA-256: {actual_hash}).")
    
    # Check deterministic checks
    checks = receipt.get("deterministic_checks", [])
    failed_checks = [c for c in checks if c.get("outcome") == "FAIL"]
    
    if failed_checks:
        eprint(f"[WARN] Receipt contains {len(failed_checks)} failed deterministic checks.")
    
    # Check unverified records
    facts = receipt.get("extracted_facts", [])
    unverified = [f for f in facts if f.get("status") != "SUPPORTED_TEXT"]
    
    if unverified:
        eprint(f"[WARN] Receipt contains {len(unverified)} facts without supported text evidence.")
        
    global_status = receipt.get("global_status")
    print(f"[INFO] Receipt global status is {global_status}.")
    
    print("[PASS] Receipt verified successfully offline.")
    return 0
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone offline Evidence Receipt verifier.")
    parser.add_argument("receipt", type=Path, help="Path to the receipt JSON file.")
    parser.add_argument("--source", type=Path, required=True, help="Path to the original source document.")
    
    args = parser.parse_args()
    
    if not args.receipt.exists():
        eprint(f"[FAIL] Receipt file not found: {args.receipt}")
        sys.exit(1)
        
    if not args.source.exists():
        eprint(f"[FAIL] Source file not found: {args.source}")
        sys.exit(1)
        
    sys.exit(verify_receipt(args.receipt, args.source))
