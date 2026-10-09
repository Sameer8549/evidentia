# Evidentia Backend

Evidentia — Make AI show its evidence. This is the complete backend system for multimodal verifiable intelligence processing.

## 🚀 Setup and Installation

Follow these steps exactly to prepare your local development environment.

### 1. Python Environment
Install Python 3.11+. We use Poetry for dependency management.
```powershell
poetry install
```

### 2. Install and Configure Tesseract OCR
Tesseract is a required system-level dependency.
- **Windows**: Download and install the Tesseract executable (e.g., from UB-Mannheim).
- Verify the English language pack (`eng`) is installed.
- Open your `.env` file (see step 4) and configure the `EVIDENTIA_TESSERACT_CMD` path to point exactly to your `tesseract.exe`.

### 3. Install Ollama and Pull Gemma 4
The application performs real local vision inference using Gemma 4.
- Install [Ollama](https://ollama.com).
- Start the Ollama server locally.
- Pull the Gemma 4 model:
  ```powershell
  ollama pull gemma4:e4b
  ```

### 4. Environment Configuration
Copy the provided `.env.example` file to create your local configuration:
```powershell
cp .env.example .env
```
Ensure that `EVIDENTIA_OLLAMA_MODEL` is set to `gemma4:e4b` (or your configured model) and that `EVIDENTIA_TESSERACT_CMD` is accurate.

---

## 💻 Running the Demo Workflow

The backend exposes APIs for uploading documents, inspecting them (OCR + Inference + Checking), retrieving results, and validating integrity.

### 5. Start the API Server and Run Health Checks
Run the FastAPI application via Uvicorn:
```powershell
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000
```
*(Optionally run `poetry run ruff check app tests verify.py` to check for lint issues).*

In a new PowerShell window, test if the API is live and dependencies are ready:
```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health/live
Invoke-RestMethod -Uri http://127.0.0.1:8000/health/ready
```

### 6. Upload a Test Document
Submit an image or PDF to the ingestion API:
```powershell
$response = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/ingest -Method Post -Form @{file=(Get-Item -Path .\sample_notice.pdf)}
$ingestionId = $response.ingestion_id
Write-Output "Ingestion ID: $ingestionId"
```

### 7. Inspect the Document (Asynchronous Job)
Start the background inspection job:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/inspect/$ingestionId/job?fetch_resources=true" -Method Post
```
Poll the job status until it says "completed":
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/inspect/$ingestionId/job"
```
*(Alternatively, you can call `POST /api/inspect/$ingestionId` to block synchronously until complete).*

### 8. Retrieve the Evidence Receipt
Once inspection is completed, download the receipt:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/inspect/$ingestionId/receipt" | ConvertTo-Json -Depth 10 | Out-File "receipt.json"
```

### 9. Verify the Receipt Offline
Use the independent `verify.py` script to re-verify the digest and source hash without LLM or network access:
```powershell
poetry run python verify.py receipt.json --source sample_notice.pdf
```

### 10. Test Source and Receipt Tampering
Prove the system's integrity by attempting to forge the document or receipt:

**Tamper the source:**
```powershell
Add-Content -Path sample_notice.pdf -Value "tamper data"
poetry run python verify.py receipt.json --source sample_notice.pdf
# Expected: FAIL - Source hash mismatch!
```

**Tamper the receipt:**
```powershell
(Get-Content receipt.json).Replace('"COMPLETED"', '"FAKE_STATUS"') | Set-Content receipt.json
poetry run python verify.py receipt.json --source sample_notice.pdf
# Expected: FAIL - Receipt digest mismatch!
```

### 11. Explore the API Docs
A full OpenAPI documentation UI is provided by FastAPI. Visit:
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) in your browser.

---

## 🧪 Testing

Run all unit and End-to-End integration tests using Pytest:
```powershell
poetry run pytest -v
```
*Note: Real OCR and Multimodal integration tests run dynamically if dependencies are met. They skip safely if unavailable, ensuring CI pipelines stay green while allowing strict local validation.*
