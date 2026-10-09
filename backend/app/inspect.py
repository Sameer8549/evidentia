from fastapi import APIRouter, HTTPException
from pathlib import Path
import json

from app.config import settings
from app.ocr import perform_ocr
from app.ollama_client import OllamaClient
from app.evidence import match_claim_to_evidence, run_deterministic_checks, EvidenceRecord
from app.receipt import EvidenceReceipt, ReceiptMetadata, ReceiptProcessing
from app.analyze import PageAnalysisSchema
from app.resources import enrich_resources

router = APIRouter()

@router.post("/api/inspect/{ingestion_id}")
async def run_inspection(ingestion_id: str, fetch_resources: bool = False):
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
        # Note: perform_ocr usually returns a Response when called via router, but we can await it
        ocr_response_obj = await perform_ocr(ingestion_id)
        # However, perform_ocr returns OCRResponse which has .pages
        ocr_results = getattr(ocr_response_obj, 'pages', [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")
        
    # 2. Run Analyze
    client = OllamaClient()
    try:
        await client.check_health()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama/Model error: {e}")
        
    from app.analyze import ANALYSIS_PROMPT

    page_files = sorted([f for f in ingestion_dir.iterdir() if f.name.startswith("page_") and f.name.endswith(".png")])
    if not page_files:
        original_path = ingestion_dir / "original"
        if not original_path.exists():
            raise HTTPException(status_code=400, detail="No pages or original file available for analysis.")
        page_files = [original_path]
        
    analysis_results = []
    global_status = "COMPLETED"
    
    for idx, page_path in enumerate(page_files):
        try:
            analysis_pydantic = await client.analyze_document_page(
                image_path=page_path, 
                prompt=ANALYSIS_PROMPT, 
                schema_class=PageAnalysisSchema
            )
            analysis_results.append(analysis_pydantic)
        except Exception as e:
            global_status = "PARTIAL"
            analysis_results.append(None)
            
    if all(a is None for a in analysis_results):
        # We must not output a receipt if everything failed
        raise HTTPException(status_code=500, detail="Analysis failed on all pages.")
        
    # 3. Aggregate facts and match evidence
    extracted_facts = []
    actionable_guidance = []
    
    for analysis in analysis_results:
        if not analysis:
            continue
            
        actionable_guidance.extend(analysis.actionable_guidance)
        
        # Iterate through relevant arrays
        for date_item in analysis.dates_and_deadlines:
            record = match_claim_to_evidence(
                candidate_value=date_item.fact_description,
                quotation=date_item.quotation,
                fact_type="dates_and_deadlines",
                ocr_pages=ocr_results
            )
            extracted_facts.append(record)
            
        for doc_item in analysis.required_documents:
            record = match_claim_to_evidence(
                candidate_value=doc_item.fact_description,
                quotation=doc_item.quotation,
                fact_type="required_documents",
                ocr_pages=ocr_results
            )
            extracted_facts.append(record)
            
        for elig_item in analysis.eligibility_criteria:
            record = match_claim_to_evidence(
                candidate_value=elig_item.fact_description,
                quotation=elig_item.quotation,
                fact_type="eligibility_criteria",
                ocr_pages=ocr_results
            )
            extracted_facts.append(record)
            
        for fee_item in analysis.fees_and_amounts:
            record = match_claim_to_evidence(
                candidate_value=fee_item.fact_description,
                quotation=fee_item.quotation,
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
    
    # Enrich resources if requested
    resources = enrich_resources(actionable_guidance) if fetch_resources else []
    
    # use first valid analysis for summary
    valid_analysis = next((a for a in analysis_results if a is not None), None)
    
    receipt = EvidenceReceipt(
        metadata=receipt_meta,
        processing=receipt_proc,
        document_summary=valid_analysis.plain_language_summary if valid_analysis else "No summary available.",
        document_purpose=valid_analysis.document_purpose if valid_analysis else "Unknown",
        extracted_facts=extracted_facts,
        deterministic_checks=checks,
        actionable_guidance=[step.model_dump() for step in actionable_guidance],
        resources=[r.model_dump() for r in resources],
        global_status=global_status
    )
    
    receipt.receipt_digest = receipt.generate_digest()
    
    # Save receipt
    receipt_path = ingestion_dir / "receipt.json"
    with open(receipt_path, 'w', encoding='utf-8') as f:
        f.write(receipt.model_dump_json(indent=2))
        
    return receipt.model_dump()
