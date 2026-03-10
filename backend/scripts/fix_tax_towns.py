#!/usr/bin/env python3
"""Fix Tax Delinquency records with incorrect town_id."""
import asyncio, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip('/')
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

async def main():
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as c:
        # Fetch all Tax Delinquency records
        r = await c.get(f"{SUPABASE_URL}/rest/v1/municipal_documents",
            headers=headers,
            params={"doc_type": "eq.Tax Delinquency", "select": "id,title,town_id"})
        records = r.json()
        print(f"Found {len(records)} Tax Delinquency records")

        towns = ["brookline","lexington","lincoln","natick","needham","newton","wayland"]
        updates = 0
        for rec in records:
            title = (rec.get("title") or "").lower()
            matched = next((t for t in towns if t in title), None)
            if not matched:
                matched = "brookline"  # fallback for East Boston / unknown
            
            if rec.get("town_id") != matched:
                print(f"  {rec['id'][:8]}... {rec.get('town_id')} -> {matched}")
                pr = await c.patch(
                    f"{SUPABASE_URL}/rest/v1/municipal_documents?id=eq.{rec['id']}",
                    headers=headers, json={"town_id": matched})
                if pr.status_code in (200, 204):
                    updates += 1

        print(f"\nUpdated {updates} records")
        # Verify
        v = await c.get(f"{SUPABASE_URL}/rest/v1/municipal_documents",
            headers=headers,
            params={"doc_type": "eq.Tax Delinquency", "town_id": "is.null", "select": "id"})
        print(f"NULL town_id remaining: {len(v.json())}")

if __name__ == "__main__":
    asyncio.run(main())
