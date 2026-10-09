import json
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from app.evidence import EvidenceRecord, DeterministicCheck

class ReceiptMetadata(BaseModel):
    receipt_id: str
    ingestion_id: str
    creation_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    source_sha256: str
    filename: str
    file_type: str
    page_count: int
    
class ReceiptProcessing(BaseModel):
    ocr_engine: str = "tesseract"
    ocr_language: str = "eng"
    model_provider: str = "ollama"
    model_tag: str
    pipeline_version: str = "1.0.0"

class EvidenceReceipt(BaseModel):
    schema_version: str = "1.0.0"
    metadata: ReceiptMetadata
    processing: ReceiptProcessing
    document_summary: Optional[str] = None
    document_purpose: Optional[str] = None
    extracted_facts: List[EvidenceRecord] = []
    deterministic_checks: List[DeterministicCheck] = []
    actionable_guidance: List[Dict[str, Any]] = []
    resources: List[Any] = [] # List[Resource]
    global_status: str
    receipt_digest: Optional[str] = None
    
    def generate_digest(self) -> str:
        # A simple digest covering key structural parts to detect tampering
        data = self.model_dump(mode="json")
        data.pop("receipt_digest", None)
        canonical = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

