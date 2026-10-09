from fastapi import APIRouter, HTTPException
from pathlib import Path
import json

from app.config import settings
from app.ocr import process_ocr
from app.analyze import analyze_document_page
from app.ollama_client import OllamaClient
from app.evidence import match_claim_to_evidence, run_deterministic_checks, EvidenceRecord
from app.receipt import EvidenceReceipt, ReceiptMetadata, ReceiptProcessing
from app.schemas import PageAnalysisSchema

router = APIRouter()

@router.post("/api/inspect/{ingestion_id}")
async def run_inspection(ingestion_id: str):
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    if not ingestion_dir.exists():
        raise HTTPException(status_code=404, detail="Ingestion ID not found")
        
    meta_file = ingestion_dir / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="Ingestion metadata not found")
        
    with open(meta_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
        
    # 1. Run OCR
    try:
        ocr_results = process_ocr(ingestion_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")
        
    # 2. Run Analyze
    client = OllamaClient()
    try:
        await client.check_health()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama/Model error: {e}")
        
    page_files = sorted([f for f in ingestion_dir.iterdir() if f.name.startswith("page_") and f.name.endswith(".png")])
    if not page_files:
        raise HTTPException(status_code=400, detail="No pages available for analysis.")
        
    analysis_results = []
    global_status = "COMPLETED"
    
    for idx, page_path in enumerate(page_files):
        try:
            analysis_dict = await client.analyze_document_page(page_path, PageAnalysisSchema)
            analysis_results.append(analysis_dict)
        except Exception as e:
            global_status = "PARTIAL"
            analysis_results.append(None)
            
    if all(a is None for a in analysis_results):
        global_status = "FAILED"
        raise HTTPException(status_code=500, detail="Analysis failed on all pages.")
        
    # 3. Aggregate facts and match evidence
    extracted_facts = []
    actionable_guidance = []
    
    for analysis in analysis_results:
        if not analysis:
            continue
            
        actionable_guidance.extend(analysis.get("actionable_guidance", []))
        
        # Iterate through relevant arrays
        for date_item in analysis.get("dates_and_deadlines", []):
            record = match_claim_to_evidence(
                candidate_value=date_item.get("fact_description", ""),
                quotation=date_item.get("candidate_quotation"),
                fact_type="dates_and_deadlines",
                ocr_pages=ocr_results
            )
            extracted_facts.append(record)
            
        for doc_item in analysis.get("required_documents", []):
            record = match_claim_to_evidence(
                candidate_value=doc_item.get("fact_description", ""),
                quotation=doc_item.get("candidate_quotation"),
                fact_type="required_documents",
                ocr_pages=ocr_results
            )
            extracted_facts.append(record)
            
        for elig_item in analysis.get("eligibility_criteria", []):
            record = match_claim_to_evidence(
                candidate_value=elig_item.get("fact_description", ""),
                quotation=elig_item.get("candidate_quotation"),
                fact_type="eligibility_criteria",
                ocr_pages=ocr_results
            )
            extracted_facts.append(record)
            
        for fee_item in analysis.get("fees_and_amounts", []):
            record = match_claim_to_evidence(
                candidate_value=fee_item.get("fact_description", ""),
                quotation=fee_item.get("candidate_quotation"),
                fact_type="fees_and_amounts",
                ocr_pages=ocr_results
            )
            extracted_facts.append(record)

    # 4. Run Deterministic checks
    checks = run_deterministic_checks(extracted_facts)
    
    # Generate Receipt
    receipt_meta = ReceiptMetadata(
        receipt_id=f"rec-{ingestion_id}",
        ingestion_id=ingestion_id,
        source_sha256=metadata.get("sha256", "unknown"),
        filename=metadata.get("original_filename", "unknown"),
        file_type=metadata.get("content_type", "unknown"),
        page_count=metadata.get("pages", len(page_files))
    )
    
    receipt_proc = ReceiptProcessing(
        model_tag=client.model
    )
    
    # use first valid analysis for summary
    valid_analysis = next((a for a in analysis_results if a is not None), {})
    
    receipt = EvidenceReceipt(
        metadata=receipt_meta,
        processing=receipt_proc,
        document_summary=valid_analysis.get("plain_language_summary"),
        document_purpose=valid_analysis.get("document_purpose"),
        extracted_facts=extracted_facts,
        deterministic_checks=checks,
        actionable_guidance=actionable_guidance,
        global_status=global_status
    )
    
    # Save receipt
    receipt_path = ingestion_dir / "receipt.json"
    with open(receipt_path, 'w', encoding='utf-8') as f:
        f.write(receipt.model_dump_json(indent=2))
        
    return receipt.model_dump()
