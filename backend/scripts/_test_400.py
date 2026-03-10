import httpx, os, json, sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(project_root / ".env", override=True)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

headers = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

url = f"{SUPABASE_URL}/rest/v1/municipal_documents?on_conflict=content_hash"
doc = {
    "town_id": "brookline",
    "doc_type": "Tax Taking",
    "title": "Tax Taking: test",
    "content_hash": "test_hash_123",
    "mentions": {"status": "Tax Taking Recorded"}
}

res = httpx.post(url, headers=headers, json=doc)
print("STATUS:", res.status_code)
print("RESPONSE:", res.text)
