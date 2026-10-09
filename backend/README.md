# Evidentia Backend

## Dependencies and Setup

### 1. Python Environment
- Install Python 3.11+
- Install dependencies using Poetry:
  ```bash
  poetry install
  ```
  (Alternatively, use `pip install -r requirements.txt` if maintaining standard pip).

### 2. Tesseract OCR (Required for OCR functionality)
Tesseract is a required system-level dependency.
- **Windows**: Download and install the Tesseract executable (e.g., from UB-Mannheim).
- Verify the English language pack (`eng`) is installed.
- Open `.env` and set the path to your executable if it's not in your system `PATH`:
  ```env
  EVIDENTIA_TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
  ```
- **Linux/Mac**: Install via your package manager (e.g., `apt install tesseract-ocr`). `EVIDENTIA_TESSERACT_CMD` can be left as `tesseract`.

### 3. Environment Variables
Copy `.env.example` to `.env` and adjust settings. 

## Running the API
Start the server using uvicorn:
```bash
poetry run uvicorn app.main:app --reload
```

## API Usage

### 1. Document Ingestion
**Endpoint**: `POST /api/ingest`
- Send a multipart form upload with a file (PDF, PNG, JPEG, WEBP).
- Returns an `ingestion_id`, detected type, size, SHA-256 hash, and dimensions.

### 2. OCR Processing
**Endpoint**: `POST /api/ocr/{ingestion_id}`
- Triggers Tesseract OCR on the previously ingested document.
- Returns a structured response containing:
  - `page_index` (0-based)
  - Full reconstructed text
  - Granular word-level coordinate boundaries mapping directly to the pixel space (`x`, `y`, `width`, `height`).
  - Coordinate convention: Origin `(0, 0)` is the top-left corner of the image.
  - Character alignment spans (`char_start`, `char_end`) aligning with the reconstructed text array to assist later highlight correlation.

### 3. Multimodal Analysis (Gemma 4)
**Endpoint**: `POST /api/analyze/{ingestion_id}`
- Triggers local Gemma 4 multimodal vision inference on the ingested document.
- **Privacy Notice**: Keeps all image and processing strictly local. Documents are never transmitted to cloud services.
- Returns a structured Pydantic-validated JSON extraction containing:
  - Document summary and purpose.
  - Key dates, deadlines, criteria, and requirements.
  - Candidate quotations grounded in the text.
  - Next-step actionable guidance for community members.
- If Ollama is unreachable or the model is missing, it fails gracefully with `HTTP 503`.

## Testing
Run unit tests with pytest:
```bash
poetry run pytest
```
*Note: Real OCR and Multimodal integration tests are executed only if Tesseract and Ollama (with Gemma 4) are detected natively on the host system. Missing dependencies safely skip without causing false test failures.*

## Known Limitations
- OCR does not confirm truthfulness of recognized text; it only executes pattern recognition of document pixels.
- Blank pages or pages with exceptionally complex noise might raise empty-text warnings.
- Gemma 4 runs purely locally. Model hallucinations in JSON schema matching may trigger validation errors in complex edge cases.
