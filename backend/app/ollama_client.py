import httpx
import base64
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional

from app.main import settings

class OllamaClient:
    def __init__(self):
        self.base_url = settings.evidentia_ollama_url.rstrip("/")
        self.model = settings.evidentia_ollama_model
        self.timeout = httpx.Timeout(600.0) # 10 mins for heavy vision model processing
        
    async def check_health(self):
        """Check if Ollama is reachable and model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                tags = resp.json().get("models", [])
                
                model_names = [m.get("name") for m in tags]
                if self.model not in model_names:
                    # sometimes the tag is returned without :latest if it's implicitly latest
                    # let's be lenient or check properly
                    if not any(m.startswith(self.model.split(":")[0]) for m in model_names):
                        raise ValueError(f"Model {self.model} is not available in Ollama.")
                        
                return True
        except httpx.RequestError:
            raise ValueError(f"Ollama is not reachable at {self.base_url}.")
            
    async def analyze_document_page(self, image_path: Path, prompt: str, schema_class: type[BaseModel]) -> BaseModel:
        """Analyze a single page image with the configured model."""
        with open(image_path, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode("utf-8")
            
        payload = {
            "model": self.model,
            "format": schema_class.model_json_schema(),
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64_image]
                }
            ],
            "options": {
                "num_ctx": 8192
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                
                data = response.json()
                content = data.get("message", {}).get("content", "")
                
                try:
                    return schema_class.model_validate_json(content)
                except ValidationError as ve:
                    raise ValueError(f"Model returned malformed JSON structure: {str(ve)}")
                    
        except httpx.RequestError as e:
            raise ValueError(f"Failed to connect to Ollama: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Ollama returned HTTP error: {e.response.status_code}")
