import hashlib
import os
import shutil
import uuid
import re
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from pydantic import BaseModel
import fitz  # PyMuPDF

from app.main import settings

router = APIRouter()

class IngestionResponse(BaseModel):
    ingestion_id: str
    filename: str
    detected_type: str
    size: int
    hash: str
    page_count: int
    page_dimensions: list[dict[str, float]]

def validate_magic_bytes(header: bytes) -> str | None:
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
        return "image/webp"
    return None

def sanitize_filename(filename: str) -> str:
    # Remove any path traversal components
    filename = os.path.basename(filename)
    # Allow alphanumeric, dot, dash, underscore
    filename = re.sub(r'[^a-zA-Z0-9.\-_]', '_', filename)
    if not filename:
        return "uploaded_file"
    return filename

@router.post("/ingest", response_model=IngestionResponse)
async def ingest_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")
    
    sanitized_filename = sanitize_filename(file.filename)
    ingestion_id = str(uuid.uuid4())
    
    # Secure temp dir inside configured data dir
    data_dir = Path(settings.evidentia_data_dir).resolve()
    ingestion_dir = data_dir / ingestion_id
    
    # Ensure ingestion_dir is actually inside data_dir (path traversal check)
    if not str(ingestion_dir).startswith(str(data_dir)):
        raise HTTPException(status_code=400, detail="Invalid data directory path.")
        
    os.makedirs(ingestion_dir, exist_ok=True)
    temp_file_path = ingestion_dir / "original"

    try:
        header = await file.read(2048)
        detected_type = validate_magic_bytes(header)
        
        if not detected_type:
            raise HTTPException(status_code=415, detail="Unsupported file format.")
            
        await file.seek(0)
        
        sha256_hash = hashlib.sha256()
        file_size = 0
        
        with open(temp_file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > settings.evidentia_max_upload_mb * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"File exceeds {settings.evidentia_max_upload_mb} MB limit.")
                f.write(chunk)
                sha256_hash.update(chunk)
                
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Empty file upload.")
            
        file_hash = sha256_hash.hexdigest()
        
        page_count = 1
        page_dimensions = []
        
        if detected_type == "application/pdf":
            try:
                with open(temp_file_path, "rb") as f:
                    pdf_data = f.read()
                with fitz.open(stream=pdf_data, filetype="pdf") as doc:
                    page_count = len(doc)
                    if page_count > settings.evidentia_max_pages:
                        raise HTTPException(status_code=413, detail=f"PDF exceeds {settings.evidentia_max_pages} pages limit.")
                    
                    for i in range(page_count):
                        page = doc.load_page(i)
                        rect = page.rect
                        page_dimensions.append({"width": rect.width, "height": rect.height})
                        # Rendering the PDF page to ensure it's valid and as required by prompt
                        pix = page.get_pixmap()
                        pix.save(ingestion_dir / f"page_{i}.png")
            except fitz.FileDataError:
                raise HTTPException(status_code=422, detail="Malformed PDF file.")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Error processing PDF: {str(e)}")
        else:
            # For images, we can optionally use fitz to get dimensions or just record dummy for now,
            # but fitz supports images too.
            try:
                with open(temp_file_path, "rb") as f:
                    img_data = f.read()
                with fitz.open(stream=img_data, filetype="png") as doc:
                    page = doc.load_page(0)
                    rect = page.rect
                    page_dimensions.append({"width": rect.width, "height": rect.height})
            except Exception:
                # If fitz fails on image, just provide empty dimensions
                pass
                
        return IngestionResponse(
            ingestion_id=ingestion_id,
            filename=sanitized_filename,
            detected_type=detected_type,
            size=file_size,
            hash=file_hash,
            page_count=page_count,
            page_dimensions=page_dimensions
        )

    except Exception:
        # Cleanup on failure
        if ingestion_dir.exists():
            shutil.rmtree(ingestion_dir, ignore_errors=True)
        raise
