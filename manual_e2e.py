import requests
import time
import sys

BASE_URL = "http://127.0.0.1:8000"

print("1. Checking health...")
live = requests.get(f"{BASE_URL}/health/live")
ready = requests.get(f"{BASE_URL}/health/ready")
print("Live:", live.json())
print("Ready:", ready.json())
if ready.status_code != 200:
    print("Dependencies not ready!")
    sys.exit(1)

print("2. Uploading document...")
with open("sample_notice.png", "rb") as f:
    files = {"file": ("sample_notice.png", f, "image/png")}
    res = requests.post(f"{BASE_URL}/api/ingest", files=files)
res.raise_for_status()
ingest_data = res.json()
print("Ingested:", ingest_data)
ingestion_id = ingest_data["ingestion_id"]

print("3. Triggering inspect job...")
res = requests.post(f"{BASE_URL}/api/inspect/{ingestion_id}/job")
res.raise_for_status()

print("4. Polling job...")
while True:
    res = requests.get(f"{BASE_URL}/api/inspect/{ingestion_id}/job")
    job = res.json()
    print(f"Status: {job['status']}")
    if job["status"] in ["completed", "failed"]:
        break
    time.sleep(2)

print("Job result:", job)
if job["status"] == "failed":
    print("Inspection failed!")
    sys.exit(1)

print("5. Getting receipt...")
res = requests.get(f"{BASE_URL}/api/inspect/{ingestion_id}/receipt")
res.raise_for_status()
receipt = res.json()
print("Receipt retrieved successfully.")

with open("receipt.json", "w") as f:
    import json
    json.dump(receipt, f, indent=2)

print("6. Verifying receipt against original source via API...")
with open("receipt.json", "rb") as f1, open("sample_notice.png", "rb") as f2:
    files = {
        "receipt_file": ("receipt.json", f1, "application/json"),
        "source_file": ("sample_notice.png", f2, "image/png")
    }
    res = requests.post(f"{BASE_URL}/api/verify", files=files)
res.raise_for_status()
print("Verification API Result:", res.json())
