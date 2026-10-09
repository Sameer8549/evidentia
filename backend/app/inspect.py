from fastapi import APIRouter, HTTPException, BackgroundTasks, File, UploadFile
from fastapi.responses import JSONResponse
from pathlib import Path
import json
import asyncio

from app.config import settings
from app.ocr import perform_ocr
from app.ollama_client import OllamaClient
from app.evidence import match_claim_to_evidence, run_deterministic_checks, EvidenceRecord
from app.receipt import EvidenceReceipt, ReceiptMetadata, ReceiptProcessing
from app.analyze import PageAnalysisSchema, ANALYSIS_PROMPT
from app.resources import enrich_resources
from app.jobs import init_job, update_job_stage, update_job_progress, load_job

router = APIRouter()

async def _run_inspection_task(ingestion_id: str, fetch_resources: bool):
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    if not ingestion_dir.exists():
        update_job_stage(ingestion_id, "failed", status="failed", error="Ingestion ID not found")
        return
        
    meta_file = ingestion_dir / "metadata.json"
    if not meta_file.exists():
        update_job_stage(ingestion_id, "failed", status="failed", error="Ingestion metadata not found")
        return
        
    with open(meta_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
        
    # 1. Run OCR
    update_job_stage(ingestion_id, "ocr")
    try:
        ocr_response_obj = await perform_ocr(ingestion_id)
        ocr_results = getattr(ocr_response_obj, 'pages', [])
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"OCR failed: {e}")
        return
        
    # 2. Run Analyze
    update_job_stage(ingestion_id, "analyzing")
    client = OllamaClient()
    try:
        await client.check_health()
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Ollama/Model error: {e}")
        return
        
    page_files = sorted([f for f in ingestion_dir.iterdir() if f.name.startswith("page_") and f.name.endswith(".png")])
    if not page_files:
        original_path = ingestion_dir / "original"
        if not original_path.exists():
            update_job_stage(ingestion_id, "failed", status="failed", error="No pages or original file available for analysis.")
            return
        page_files = [original_path]
        
    analysis_results = []
    global_status = "COMPLETED"
    total_pages = len(page_files)
    
    for idx, page_path in enumerate(page_files):
        update_job_progress(ingestion_id, pages_processed=idx, total_pages=total_pages)
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
            
    update_job_progress(ingestion_id, pages_processed=total_pages, total_pages=total_pages)
            
    if all(a is None for a in analysis_results):
        update_job_stage(ingestion_id, "failed", status="failed", error="Analysis failed on all pages.")
        return
        
    # 3. Aggregate facts and match evidence
    update_job_stage(ingestion_id, "matching_evidence")
    extracted_facts = []
    actionable_guidance = []
    
    for analysis in analysis_results:
        if not analysis:
            continue
            
        actionable_guidance.extend(analysis.actionable_guidance)
        
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
    update_job_stage(ingestion_id, "generating_receipt")
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
    
    resources = enrich_resources(actionable_guidance) if fetch_resources else []
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
    receipt_path = ingestion_dir / "receipt.json"
    with open(receipt_path, 'w', encoding='utf-8') as f:
        f.write(receipt.model_dump_json(indent=2))
        
    update_job_stage(ingestion_id, "completed", status="completed", receipt_available=True)

@router.post("/api/inspect/{ingestion_id}")
async def run_inspection(ingestion_id: str, fetch_resources: bool = False):
    """Backward-compatible synchronous inspection endpoint."""
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    if not ingestion_dir.exists():
        raise HTTPException(status_code=404, detail="Ingestion ID not found")
        
    init_job(ingestion_id)
    await _run_inspection_task(ingestion_id, fetch_resources)
    
    job = load_job(ingestion_id)
    if job and job.status == "failed":
        raise HTTPException(status_code=500, detail=job.errors[0] if job.errors else "Inspection failed")
        
    receipt_path = Path(settings.evidentia_data_dir) / ingestion_id / "receipt.json"
    if not receipt_path.exists():
        raise HTTPException(status_code=500, detail="Receipt was not generated.")
        
    with open(receipt_path, 'r', encoding='utf-8') as f:
        return json.load(f)

@router.post("/api/inspect/{ingestion_id}/job")
async def start_inspection_job(ingestion_id: str, background_tasks: BackgroundTasks, fetch_resources: bool = False):
    """Start an inspection job asynchronously."""
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    if not ingestion_dir.exists():
        raise HTTPException(status_code=404, detail="Ingestion ID not found")
        
    job = load_job(ingestion_id)
    if not job:
        job = init_job(ingestion_id)
        background_tasks.add_task(_run_inspection_task, ingestion_id, fetch_resources)
    elif job.status == "failed":
        # Allow restarting a failed job
        job = init_job(ingestion_id)
        background_tasks.add_task(_run_inspection_task, ingestion_id, fetch_resources)
        
    return job.model_dump()

@router.get("/api/inspect/{ingestion_id}/job")
async def get_inspection_job(ingestion_id: str):
    """Get the status of an inspection job."""
    job = load_job(ingestion_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump()

@router.get("/api/inspect/{ingestion_id}/receipt")
async def get_receipt(ingestion_id: str):
    """Download the receipt."""
    receipt_path = Path(settings.evidentia_data_dir) / ingestion_id / "receipt.json"
    if not receipt_path.exists():
        raise HTTPException(status_code=404, detail="Receipt not found")
    with open(receipt_path, 'r', encoding='utf-8') as f:
        return json.load(f)

@router.post("/api/verify")
async def verify_receipt(receipt_file: UploadFile = File(...), source_file: UploadFile = File(...)):
    """Verify a receipt against a source file."""
    import tempfile
    import os
    import subprocess
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_receipt = Path(tmpdir) / "receipt.json"
        tmp_source = Path(tmpdir) / source_file.filename
        
        with open(tmp_receipt, "wb") as f:
            f.write(await receipt_file.read())
            
        with open(tmp_source, "wb") as f:
            f.write(await source_file.read())
            
        # Use python to run verify.py
        result = subprocess.run([
            "python", "verify.py", str(tmp_receipt), "--source", str(tmp_source)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            return JSONResponse(status_code=400, content={"verified": False, "details": result.stderr or result.stdout})
            
        return {"verified": True, "details": result.stdout}
