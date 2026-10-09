from typing import List, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class Resource(BaseModel):
    name: str
    url: str
    source_type: str # e.g. "official_portal", "agency", "dataset"
    retrieval_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    status: str = "retrieved" # retrieved, failed, skipped

def enrich_resources(actionable_guidance: List[Any]) -> List[Resource]:
    """
    Optional enrichment step to find real-world resources for community guidance.
    In this offline/local release, it returns curated offline templates or skips.
    If external APIs are configured, this is where they would be called.
    """
    resources = []
    
    for item in actionable_guidance:
        if hasattr(item, "model_dump"):
            item_dict = item.model_dump()
        elif isinstance(item, dict):
            item_dict = item
        else:
            continue
            
        instruction = item_dict.get("instruction", "").lower()
        if "apply" in instruction or "submit" in instruction:
            resources.append(Resource(
                name="Local Government Portal Search (Template)",
                url="https://www.india.gov.in/",
                source_type="official_portal",
                status="skipped - offline mode"
            ))
            
    return resources
