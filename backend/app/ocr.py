from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import pytesseract
from PIL import Image
from typing import List

from app.config import settings

router = APIRouter()

class OCRWord(BaseModel):
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    char_start: int
    char_end: int

class OCRPageResult(BaseModel):
    page_index: int
    text: str
    words: List[OCRWord]
    width: int
    height: int
    engine: str = "tesseract"
    language: str = "eng"
    warnings: List[str] = []

class OCRResponse(BaseModel):
    ingestion_id: str
    pages: List[OCRPageResult]
    status: str

@router.post("/ocr/{ingestion_id}", response_model=OCRResponse)
async def perform_ocr(ingestion_id: str):
    data_dir = Path(settings.evidentia_data_dir).resolve()
    ingestion_dir = data_dir / ingestion_id
    
    try:
        ingestion_dir.relative_to(data_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ingestion ID.")
        
    if not ingestion_dir.exists() or not ingestion_dir.is_dir():
        raise HTTPException(status_code=404, detail="Ingestion ID not found.")
        
    pytesseract.pytesseract.tesseract_cmd = settings.evidentia_tesseract_cmd
    
    try:
        # Check if tesseract is available
        pytesseract.get_tesseract_version()
    except Exception as e:
        raise HTTPException(status_code=503, detail="Tesseract OCR engine is not available.")
        
    pages = []
    
    # Determine if it's a PDF (has page_*.png) or an image (only original)
    page_files = sorted(list(ingestion_dir.glob("page_*.png")), key=lambda p: int(p.stem.split("_")[1]))
    
    if not page_files:
        # It's an image
        original_path = ingestion_dir / "original"
        if not original_path.exists():
            raise HTTPException(status_code=404, detail="Source file missing.")
        try:
            page_result = process_image(original_path, 0)
            pages.append(page_result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OCR processing failed: {str(e)}")
    else:
        # It's a PDF
        for idx, page_file in enumerate(page_files):
            try:
                page_result = process_image(page_file, idx)
                pages.append(page_result)
            except Exception as e:
                # If one page fails, we can either fail the whole document or append a warning.
                # Let's fail the document for now as requested: "An unreadable or blank page must not cause the entire document to crash" wait, 
                # Actually, the prompt says: "An unreadable or blank page must not cause the entire document to crash. Report the result accurately."
                pages.append(OCRPageResult(
                    page_index=idx,
                    text="",
                    words=[],
                    width=0,
                    height=0,
                    warnings=[f"Failed to process page: {str(e)}"]
                ))
                
    return OCRResponse(ingestion_id=ingestion_id, pages=pages, status="success")


def process_image(image_path: Path, page_index: int) -> OCRPageResult:
    warnings = []
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            # Get verbose data including boxes, confidences, line and word numbers
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang='eng')
    except pytesseract.TesseractError as e:
        if "Failed loading language" in str(e):
            raise HTTPException(status_code=503, detail="Missing English language data for Tesseract.")
        raise
    except Exception as e:
        raise
        
    words = []
    reconstructed_text_blocks = []
    char_offset = 0
    
    # Tesseract output lists all blocks, paragraphs, lines, and words.
    # Level 5 is word. We will group words by block/paragraph/line to insert spaces/newlines.
    
    current_block = None
    current_par = None
    current_line = None
    
    n_boxes = len(data['level'])
    
    for i in range(n_boxes):
        if data['level'][i] == 5: # Word level
            text = data['text'][i].strip()
            
            # Tesseract often emits empty text for structural elements or noise
            if not text:
                continue
                
            block_num = data['block_num'][i]
            par_num = data['par_num'][i]
            line_num = data['line_num'][i]
            
            # Spacing logic:
            prefix = ""
            if current_block != block_num or current_par != par_num:
                if char_offset > 0:
                    prefix = "\n\n"
            elif current_line != line_num:
                if char_offset > 0:
                    prefix = "\n"
            else:
                if char_offset > 0:
                    prefix = " "
                    
            if prefix:
                reconstructed_text_blocks.append(prefix)
                char_offset += len(prefix)
                
            current_block = block_num
            current_par = par_num
            current_line = line_num
            
            start_idx = char_offset
            reconstructed_text_blocks.append(text)
            char_offset += len(text)
            end_idx = char_offset
            
            conf = float(data['conf'][i])
            
            words.append(OCRWord(
                text=text,
                x=data['left'][i],
                y=data['top'][i],
                width=data['width'][i],
                height=data['height'][i],
                confidence=conf,
                char_start=start_idx,
                char_end=end_idx
            ))
            
    full_text = "".join(reconstructed_text_blocks)
    
    if not full_text.strip():
        warnings.append("No text detected on page.")
        
    return OCRPageResult(
        page_index=page_index,
        text=full_text,
        words=words,
        width=width,
        height=height,
        warnings=warnings
    )
