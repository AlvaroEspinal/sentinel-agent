import asyncio
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from database.supabase_client import SupabaseRestClient

async def main():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
    
    if not supabase_url or not supabase_key:
        print("Missing Supabase credentials")
        return

    client = SupabaseRestClient(supabase_url, supabase_key)
    if not await client.connect():
        print("Failed to connect to Supabase")
        return

    try:
        # Check geocoded locations
        # Getting a true COUNT in PostgREST via this client might be tricky if it doesn't support 'count=exact'.
        # Let's just fetch with limit=1 but use count=exact in httpx directly.
        import httpx
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Range-Unit": "items"
        }
        
        # 1. document_locations total count
        resp = httpx.get(f"{supabase_url}/rest/v1/document_locations?select=id", headers=headers, params={"limit": 1})
        
        # PostgREST uses Prefer: count=exact header for counts
        headers_count = headers.copy()
        headers_count["Prefer"] = "count=exact"
        
        # Check for COs in documents
        resp_type_occ = httpx.get(f"{supabase_url}/rest/v1/documents?select=id&permit_type=ilike.*occupancy*", headers=headers_count, params={"limit": 1})
        type_occ_count = resp_type_occ.headers.get("Content-Range", "").split("/")[-1]

        resp_type_co = httpx.get(f"{supabase_url}/rest/v1/documents?select=id&permit_type=ilike.*c.o.*", headers=headers_count, params={"limit": 1})
        type_co_count = resp_type_co.headers.get("Content-Range", "").split("/")[-1]

        resp_desc_occ = httpx.get(f"{supabase_url}/rest/v1/documents?select=id&description=ilike.*occupancy*", headers=headers_count, params={"limit": 1})
        desc_occ_count = resp_desc_occ.headers.get("Content-Range", "").split("/")[-1]
        
        print("--- Certificates of Occupancy Check ---")
        print(f"Permits with 'occupancy' in permit_type: {type_occ_count}")
        print(f"Permits with 'c.o.' in permit_type: {type_co_count}")
        print(f"Permits with 'occupancy' in description: {desc_occ_count}")
        
        # 3. total meeting minutes
        resp_mins = httpx.get(f"{supabase_url}/rest/v1/municipal_documents?select=id", headers=headers_count, params={"limit": 1})
        mins_count = resp_mins.headers.get("Content-Range", "").split("/")[-1]
        
        # 4. total meeting minutes with LLM extraction
        resp_llm = httpx.get(f"{supabase_url}/rest/v1/municipal_documents?select=id&content_summary=not.is.null", headers=headers_count, params={"limit": 1})
        llm_count = resp_llm.headers.get("Content-Range", "").split("/")[-1]

        print("--- Scraper Status Report ---")
        print(f"LLM Extracted Minutes: {llm_count} / {mins_count}")

    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
