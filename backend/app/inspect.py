from fastapi import APIRouter, HTTPException, BackgroundTasks, File, UploadFile
from fastapi.responses import JSONResponse
from pathlib import Path
import asyncio
import hashlib
import json
import re
import subprocess
import sys

from app.config import settings
from app.ocr import perform_ocr
from app.ollama_client import OllamaClient
from app.evidence import match_claim_to_evidence, run_deterministic_checks, EvidenceRecord
from app.receipt import EvidenceReceipt, ReceiptMetadata, ReceiptProcessing
from app.analyze import PageAnalysisSchema, ANALYSIS_PROMPT
from app.resources import enrich_resources
from app.jobs import init_job, update_job_stage, update_job_progress, load_job

router = APIRouter()


def _resolve_ingestion_dir(ingestion_id: str) -> Path:
    """Resolve an ingestion directory without permitting path traversal."""
    data_dir = Path(settings.evidentia_data_dir).resolve()
    target = (data_dir / ingestion_id).resolve()
    try:
        target.relative_to(data_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid ingestion ID.") from exc
    return target


def _source_sha256(source_path: Path) -> str:
    digest = hashlib.sha256()
    with source_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _run_inspection_task(ingestion_id: str, fetch_resources: bool):
    try:
        await _run_inspection_task_inner(ingestion_id, fetch_resources)
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Unexpected error: {e}")

async def _run_inspection_task_inner(ingestion_id: str, fetch_resources: bool):
    try:
        ingestion_dir = _resolve_ingestion_dir(ingestion_id)
    except HTTPException as exc:
        update_job_stage(ingestion_id, "failed", status="failed", error=str(exc.detail))
        return
    if not ingestion_dir.exists() or not ingestion_dir.is_dir():
        update_job_stage(ingestion_id, "failed", status="failed", error="Ingestion ID not found")
        return

    meta_file = ingestion_dir / "metadata.json"
    source_path = ingestion_dir / "original"
    if not meta_file.is_file() or not source_path.is_file():
        update_job_stage(ingestion_id, "failed", status="failed", error="Source or ingestion metadata is missing")
        return

    try:
        with meta_file.open("r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
    except (OSError, json.JSONDecodeError) as exc:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Invalid ingestion metadata: {exc}")
        return

    expected_hash = metadata.get("sha256") if isinstance(metadata, dict) else None
    expected_filename = metadata.get("original_filename") if isinstance(metadata, dict) else None
    expected_type = metadata.get("content_type") if isinstance(metadata, dict) else None
    if (
        not isinstance(expected_hash, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash)
        or not isinstance(expected_filename, str)
        or not expected_filename.strip()
        or not isinstance(expected_type, str)
        or not expected_type.strip()
    ):
        update_job_stage(ingestion_id, "failed", status="failed", error="Invalid ingestion metadata: required fields or SHA-256 are missing")
        return

    try:
        actual_hash = _source_sha256(source_path)
    except OSError as exc:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Cannot read original source: {exc}")
        return
    if actual_hash.lower() != expected_hash.lower():
        update_job_stage(ingestion_id, "failed", status="failed", error="Original source hash no longer matches ingestion metadata")
        return
        
    # 1. Run OCR
    update_job_stage(ingestion_id, "ocr")
    try:
        ocr_response_obj = await perform_ocr(ingestion_id)
        ocr_results = getattr(ocr_response_obj, "pages", [])
        if not ocr_results:
            update_job_stage(ingestion_id, "failed", status="failed", error="OCR returned no pages")
            return
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"OCR failed: {e}")
        return

    # A blank/unreadable OCR page means this receipt cannot be described as a fully
    # completed text-evidence workflow even if vision inference itself succeeds.
    ocr_has_issues = any(
        bool(getattr(page, "warnings", [])) or not str(getattr(page, "text", "")).strip()
        for page in ocr_results
    )

    # 2. Run Analyze
    update_job_stage(ingestion_id, "analyzing")
    client = OllamaClient()
    try:
        await client.check_health()
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Ollama/Model error: {e}")
        return
        
    page_files = sorted(
        [f for f in ingestion_dir.iterdir() if re.fullmatch(r"page_\d+\.png", f.name)],
        key=lambda path: int(path.stem.split("_")[1]),
    )
    if not page_files:
        original_path = ingestion_dir / "original"
        if not original_path.exists():
            update_job_stage(ingestion_id, "failed", status="failed", error="No pages or original file available for analysis.")
            return
        page_files = [original_path]
        
    analysis_results = []
    global_status = "PARTIAL" if ocr_has_issues else "COMPLETED"
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
    
    fact_categories = (
        ("important_factual_details", "important_factual_details"),
        ("dates_and_deadlines", "dates_and_deadlines"),
        ("eligibility_criteria", "eligibility_criteria"),
        ("fees_and_amounts", "fees_and_amounts"),
        ("locations_and_jurisdiction", "locations_and_jurisdiction"),
        ("required_documents", "required_documents"),
        ("procedures_and_instructions", "procedures_and_instructions"),
        ("contact_information", "contact_information"),
    )
    for analysis in analysis_results:
        if analysis is None:
            continue
        actionable_guidance.extend(analysis.actionable_guidance)
        for field_name, fact_type in fact_categories:
            for item in getattr(analysis, field_name, []) or []:
                extracted_facts.append(
                    match_claim_to_evidence(
                        candidate_value=item.fact_description,
                        quotation=item.quotation,
                        fact_type=fact_type,
                        ocr_pages=ocr_results,
                    )
                )

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
        final_status = "completed" if global_status == "COMPLETED" else "partial"
        update_job_stage(ingestion_id, final_stage, status=final_status, receipt_available=True)
    except Exception as e:
        update_job_stage(ingestion_id, "failed", status="failed", error=f"Receipt generation failed: {e}")
        return

@router.post("/api/inspect/{ingestion_id}")
async def run_inspection(ingestion_id: str, fetch_resources: bool = False):
    """Backward-compatible synchronous inspection endpoint."""
    ingestion_dir = _resolve_ingestion_dir(ingestion_id)
    if not ingestion_dir.exists() or not ingestion_dir.is_dir():
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
    ingestion_dir = _resolve_ingestion_dir(ingestion_id)
    if not ingestion_dir.exists() or not ingestion_dir.is_dir():
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
    _resolve_ingestion_dir(ingestion_id)
    job = load_job(ingestion_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump()

@router.get("/api/inspect/{ingestion_id}/receipt")
async def get_receipt(ingestion_id: str):
    """Download the receipt."""
    ingestion_dir = _resolve_ingestion_dir(ingestion_id)
    receipt_path = ingestion_dir / "receipt.json"
    if not receipt_path.exists():
        raise HTTPException(status_code=404, detail="Receipt not found")
    with open(receipt_path, 'r', encoding='utf-8') as f:
        return json.load(f)

@router.post("/api/verify")
async def verify_receipt(receipt_file: UploadFile = File(...), source_file: UploadFile = File(...)):
    """Verify a receipt against a source file."""
    import tempfile

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
        
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(verify_script), str(tmp_receipt), "--source", str(tmp_source)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return JSONResponse(
                status_code=504,
                content={"verified": False, "details": "Offline receipt verification timed out."},
            )
        except OSError as exc:
            return JSONResponse(
                status_code=503,
                content={"verified": False, "details": f"Could not launch the offline verifier: {exc}"},
            )

        if result.returncode != 0:
            return JSONResponse(
                status_code=400,
                content={"verified": False, "details": result.stderr or result.stdout},
            )

        return {"verified": True, "details": result.stdout}
