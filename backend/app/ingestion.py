import hashlib
import os
import shutil
import uuid
import re
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
import fitz  # PyMuPDF
from PIL import Image, UnidentifiedImageError

from app.config import settings

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
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def sanitize_filename(filename: str) -> str:
    filename = os.path.basename(filename)
    filename = re.sub(r"[^a-zA-Z0-9.\-_]", "_", filename)
    if not filename:
        return "uploaded_file"
    return filename


@router.post("/ingest", response_model=IngestionResponse)
async def ingest_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    sanitized_filename = sanitize_filename(file.filename)
    ingestion_id = str(uuid.uuid4())

    data_dir = Path(settings.evidentia_data_dir).resolve()
    ingestion_dir = data_dir / ingestion_id

    try:
        ingestion_dir.relative_to(data_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data directory path.")

    os.makedirs(ingestion_dir, exist_ok=True)
    temp_file_path = ingestion_dir / "original"

    try:
        header = await file.read(2048)
        if len(header) == 0:
            raise HTTPException(status_code=400, detail="Empty file upload.")

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
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {settings.evidentia_max_upload_mb} MB limit.",
                    )
                f.write(chunk)
                sha256_hash.update(chunk)

        if file_size == 0:
            raise HTTPException(status_code=400, detail="Empty file upload.")

        file_hash = sha256_hash.hexdigest()

        page_count = 1
        page_dimensions = []

        if detected_type == "application/pdf":
            try:
                # Use stream to avoid Windows file lock issues
                with open(temp_file_path, "rb") as f:
                    pdf_data = f.read()

                with fitz.open(stream=pdf_data, filetype="pdf") as doc:
                    page_count = len(doc)
                    if page_count > settings.evidentia_max_pages:
                        raise HTTPException(
                            status_code=413,
                            detail=f"PDF exceeds {settings.evidentia_max_pages} pages limit.",
                        )

                    for i in range(page_count):
                        page = doc.load_page(i)
                        rect = page.rect
                        width, height = rect.width, rect.height

                        if (
                            width > settings.evidentia_max_image_dim
                            or height > settings.evidentia_max_image_dim
                        ):
                            raise HTTPException(
                                status_code=413,
                                detail=f"PDF page {i} dimensions exceed {settings.evidentia_max_image_dim}px limit.",
                            )

                        # control rendering resolution (e.g. limit to 2x zoom if safe, else 1x)
                        zoom = 2.0
                        if (width * zoom) * (
                            height * zoom
                        ) > settings.evidentia_max_image_pixels:
                            zoom = 1.0  # fallback to prevent huge alloc
                            if width * height > settings.evidentia_max_image_pixels:
                                raise HTTPException(
                                    status_code=413,
                                    detail=f"PDF page {i} pixel count exceeds limit.",
                                )

                        matrix = fitz.Matrix(zoom, zoom)
                        page_dimensions.append({"width": width, "height": height})
                        pix = page.get_pixmap(matrix=matrix)
                        pix.save(ingestion_dir / f"page_{i}.png")
            except fitz.FileDataError:
                raise HTTPException(status_code=422, detail="Malformed PDF file.")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=422, detail=f"Error processing PDF: {str(e)}"
                )
        else:
            try:
                with Image.open(temp_file_path) as img:
                    img.verify()  # Validates that it is indeed a decodable image without loading data

                with Image.open(temp_file_path) as img:
                    width, height = img.size

                    if (
                        width > settings.evidentia_max_image_dim
                        or height > settings.evidentia_max_image_dim
                    ):
                        raise HTTPException(
                            status_code=413,
                            detail=f"Image dimensions exceed {settings.evidentia_max_image_dim}px limit.",
                        )
                    if width * height > settings.evidentia_max_image_pixels:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Image pixel count exceeds {settings.evidentia_max_image_pixels} limit.",
                        )

                    page_dimensions.append({"width": width, "height": height})
                    # Ensure format matches detected magic bytes (optional but good sanity check)
                    img_format = img.format.lower()
                    if detected_type == "image/jpeg" and img_format not in [
                        "jpeg",
                        "jpg",
                    ]:
                        raise HTTPException(
                            status_code=422, detail="Mismatched image format."
                        )
                    if detected_type == "image/png" and img_format != "png":
                        raise HTTPException(
                            status_code=422, detail="Mismatched image format."
                        )
                    if detected_type == "image/webp" and img_format != "webp":
                        raise HTTPException(
                            status_code=422, detail="Mismatched image format."
                        )

            except UnidentifiedImageError:
                raise HTTPException(status_code=422, detail="Malformed image file.")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=422, detail=f"Error processing image: {str(e)}"
                )

        # cleanup successful - keeping only needed files (original, and rendered pages)
        # Note: we are keeping `original` as it might be needed for later processing (e.g. OCR PDF)

        import json

        metadata = {
            "sha256": file_hash,
            "original_filename": sanitized_filename,
            "content_type": detected_type,
            "size": file_size,
            "pages": page_count,
            "page_dimensions": page_dimensions,
        }
        with open(ingestion_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return IngestionResponse(
            ingestion_id=ingestion_id,
            filename=sanitized_filename,
            detected_type=detected_type,
            size=file_size,
            hash=file_hash,
            page_count=page_count,
            page_dimensions=page_dimensions,
        )

    except Exception:
        if ingestion_dir.exists():
            shutil.rmtree(ingestion_dir, ignore_errors=True)
        raise
