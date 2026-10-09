import os
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from PIL import Image, ImageDraw
import json

from app.config import settings
from app.analyze import PageAnalysisSchema
from app.ollama_client import OllamaClient

@pytest.fixture(autouse=True)
def setup_teardown_data_dir():
    data_dir = Path(settings.evidentia_data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    os.makedirs(data_dir, exist_ok=True)
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)

def create_mock_ollama_response():
    return {
        "document_type": "Notice",
        "document_purpose": "Community event announcement",
        "plain_language_summary": "A notice for a community event.",
        "important_factual_details": [{"fact_description": "Starts at 10 AM", "quotation": "10 AM", "is_missing_or_unknown": False}],
        "dates_and_deadlines": [],
        "eligibility_criteria": [],
        "fees_and_amounts": [],
        "locations_and_jurisdiction": [],
        "required_documents": [],
        "procedures_and_instructions": [],
        "contact_information": [],
        "warnings_and_ambiguities": [],
        "actionable_guidance": [{"step_order": 1, "instruction": "Attend event", "is_model_suggestion": False}]
    }

@pytest.mark.asyncio
@patch('app.analyze.OllamaClient.check_health')
@patch('app.analyze.OllamaClient.analyze_document_page')
async def test_analyze_mocked_success(mock_analyze, mock_health, async_client: AsyncClient):
    mock_health.return_value = True
    mock_analyze.return_value = PageAnalysisSchema.model_validate_json(json.dumps(create_mock_ollama_response()))
    
    ingestion_id = "test-analyze-123"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    img = Image.new("RGB", (100, 100), color="white")
    img.save(ingestion_dir / "page_0.png")
    
    response = await async_client.post(f"/api/analyze/{ingestion_id}")
    assert response.status_code == 200
    data = response.json()
    
    assert data["global_status"] == "COMPLETED"
    assert len(data["pages"]) == 1
    page = data["pages"][0]
    assert page["status"] == "success"
    assert page["analysis"]["document_type"] == "Notice"

@pytest.mark.asyncio
@patch('app.analyze.OllamaClient.check_health')
async def test_analyze_missing_model(mock_health, async_client: AsyncClient):
    mock_health.side_effect = ValueError("Model wrong_model:latest is not available in Ollama.")
    
    ingestion_id = "test-analyze-456"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    response = await async_client.post(f"/api/analyze/{ingestion_id}")
    assert response.status_code == 503
    assert "is not available" in response.json()["detail"]

@pytest.mark.asyncio
@patch('app.analyze.OllamaClient.check_health')
@patch('app.analyze.OllamaClient.analyze_document_page')
async def test_analyze_malformed_json(mock_analyze, mock_health, async_client: AsyncClient):
    mock_health.return_value = True
    mock_analyze.side_effect = ValueError("Model returned malformed JSON structure")
    
    ingestion_id = "test-analyze-789"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    img = Image.new("RGB", (100, 100), color="white")
    img.save(ingestion_dir / "page_0.png")
    
    response = await async_client.post(f"/api/analyze/{ingestion_id}")
    assert response.status_code == 200
    data = response.json()
    
    assert data["global_status"] == "FAILED"
    page = data["pages"][0]
    assert page["status"] == "error"
    assert "malformed JSON structure" in page["warnings"][0]

@pytest.mark.asyncio
async def test_analyze_unknown_ingestion_id(async_client: AsyncClient):
    response = await async_client.post("/api/analyze/fake-id-123")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_analyze_integration(async_client: AsyncClient):
    import os
    is_strict = os.getenv("EVIDENTIA_STRICT_E2E") == "1"
    
    client = OllamaClient()
    try:
        await client.check_health()
    except Exception as e:
        if is_strict:
            pytest.fail(f"Strict mode: Ollama must be available. {e}")
        else:
            pytest.skip("Ollama or configured model is not available in environment. Skipping integration test.")
        
    ingestion_id = "test-analyze-real"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    from PIL import ImageFont
    img = Image.new("RGB", (1600, 1200), color="white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=48)
    except TypeError:
        font = ImageFont.load_default()
        
    d.text((50,50), "COMMUNITY NOTICE", fill=(0,0,0), font=font)
    d.text((50,150), "Application deadline: 18 October 2026", fill=(0,0,0), font=font)
    d.text((50,250), "Required document: ID proof", fill=(0,0,0), font=font)
    img.save(ingestion_dir / "original", format="PNG") 
    
    response = await async_client.post(f"/api/analyze/{ingestion_id}", timeout=600.0)
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["pages"]) == 1
    page = data["pages"][0]
    if page["status"] == "error":
        print(f"INTEGRATION TEST ERROR: {page['warnings']}")
        if any("HTTP error: 500" in w for w in page["warnings"]) and not is_strict:
            pytest.skip("Ollama returned 500 on inference. Environment issue.")
        else:
            pytest.fail(f"Integration test failed on page analysis: {page['warnings']}")
            
    analysis = page.get("analysis")
    assert analysis is not None, f"Analysis failed: {page.get('warnings')}"
    
    analysis_dict = analysis if isinstance(analysis, dict) else analysis
    
    doc_type = analysis_dict.get("document_type", "").lower()
    assert doc_type, "Document type should not be entirely empty"
    
    dates = [f"{d.get('fact_description', '')} {d.get('quotation', '')}".lower() for d in analysis_dict.get("dates_and_deadlines", [])]
    has_deadline = any("18" in d or "october" in d for d in dates)
    assert has_deadline, f"Did not extract 18 October 2026. Found: {dates}"
    
    docs = [f"{d.get('fact_description', '')} {d.get('quotation', '')}".lower() for d in analysis_dict.get("required_documents", [])]
    has_docs = any("id" in d or "proof" in d for d in docs)
    assert has_docs, f"Did not extract ID proof. Found: {docs}"
