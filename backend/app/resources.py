from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class Resource(BaseModel):
    name: str
    url: str
    source_type: str # e.g. "official_portal", "agency", "dataset"
    retrieval_timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    status: str = "retrieved" # retrieved, failed, skipped

def enrich_resources(actionable_guidance: List[dict]) -> List[Resource]:
    """
    Optional enrichment step to find real-world resources for community guidance.
    In this offline/local release, it returns curated offline templates or skips.
    If external APIs are configured, this is where they would be called.
    """
    resources = []
    
    for item in actionable_guidance:
        instruction = item.get("instruction", "").lower()
        if "apply" in instruction or "submit" in instruction:
            resources.append(Resource(
                name="Local Government Portal Search (Template)",
                url="https://www.india.gov.in/",
                source_type="official_portal",
                status="skipped - offline mode"
            ))
            
    return resources
