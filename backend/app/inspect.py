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
    try:
        await _run_inspection_task_inner(ingestion_id, fetch_resources)
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Unexpected error: {e}")

async def _run_inspection_task_inner(ingestion_id: str, fetch_resources: bool):
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
    try:
        checks = run_deterministic_checks(extracted_facts)
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Deterministic checks failed: {e}")
        return
    
    # Generate Receipt
    if (not metadata.get("sha256") or metadata.get("sha256") == "unknown" or 
        not metadata.get("original_filename") or metadata.get("original_filename") == "unknown" or 
        not metadata.get("content_type") or metadata.get("content_type") == "unknown"):
        update_job_stage(ingestion_id, "failed", status="failed", error="Invalid ingestion metadata: missing required fields")
        return

    receipt_meta = ReceiptMetadata(
        receipt_id=f"rec-{ingestion_id}",
        ingestion_id=ingestion_id,
        source_sha256=metadata["sha256"],
        filename=metadata["original_filename"],
        file_type=metadata["content_type"],
        page_count=metadata.get("pages", len(page_files))
    )
    
    receipt_proc = ReceiptProcessing(
        model_tag=client.model
    )
    
    try:
        resources = enrich_resources(actionable_guidance) if fetch_resources else []
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Resource enrichment failed: {e}")
        return

    valid_analysis = next((a for a in analysis_results if a is not None), None)
    
    try:
        receipt = EvidenceReceipt(
            metadata=receipt_meta,
            processing=receipt_proc,
            document_summary=valid_analysis.plain_language_summary if valid_analysis else "No summary available.",
            document_purpose=valid_analysis.document_purpose if valid_analysis else "Unknown",
            extracted_facts=extracted_facts,
            deterministic_checks=checks,
            actionable_guidance=[step.model_dump() if hasattr(step, 'model_dump') else step for step in actionable_guidance],
            resources=[r.model_dump() for r in resources],
            global_status=global_status
        )
        
        receipt.receipt_digest = receipt.generate_digest()
        receipt_path = ingestion_dir / "receipt.json"
        with open(receipt_path, 'w', encoding='utf-8') as f:
            f.write(receipt.model_dump_json(indent=2))
            
        final_stage = "completed" if global_status == "COMPLETED" else "partial"
        update_job_stage(ingestion_id, final_stage, status="completed", receipt_available=True)
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Receipt generation failed: {e}")
        return

@router.post("/api/inspect/{ingestion_id}")
async def run_inspection(ingestion_id: str, fetch_resources: bool = False):
    """Backward-compatible synchronous inspection endpoint."""
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    if not ingestion_dir.exists():
        raise HTTPException(status_code=404, detail="Ingestion ID not found")
        
    init_job(ingestion_id)
    try:
        await _run_inspection_task(ingestion_id, fetch_resources)
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=str(e))
    
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
    import sys
    import subprocess
    
    max_bytes = settings.evidentia_max_upload_mb * 1024 * 1024
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_receipt = Path(tmpdir) / "receipt.json"
        tmp_source = Path(tmpdir) / "source_doc.bin" # Fixed safe name
        
        # Safely stream receipt
        receipt_size = 0
        with open(tmp_receipt, "wb") as f:
            while chunk := await receipt_file.read(8192):
                receipt_size += len(chunk)
                if receipt_size > max_bytes:
                    return JSONResponse(status_code=413, content={"verified": False, "details": "Receipt file exceeds size limit"})
                f.write(chunk)
                
        # Safely stream source
        source_size = 0
        with open(tmp_source, "wb") as f:
            while chunk := await source_file.read(8192):
                source_size += len(chunk)
                if source_size > max_bytes:
                    return JSONResponse(status_code=413, content={"verified": False, "details": "Source file exceeds size limit"})
                f.write(chunk)
                
        verify_script = Path(__file__).parent.parent / "verify.py"
        
        result = subprocess.run([
            sys.executable, str(verify_script), str(tmp_receipt), "--source", str(tmp_source)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            return JSONResponse(status_code=400, content={"verified": False, "details": result.stderr or result.stdout})
            
        return {"verified": True, "details": result.stdout}
