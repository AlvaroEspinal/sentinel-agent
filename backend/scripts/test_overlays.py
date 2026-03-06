"""
CLI test script for the Municipal Overlay Districts connector.

Queries public Boston ArcGIS FeatureServer overlay layers using a
bounding box around downtown Boston, prints the resulting GeoJSON,
then enriches the results with an OpenRouter LLM interpretation.

Usage:
    cd backend
    python scripts/test_overlays.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add backend/ to sys.path so imports resolve
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from scrapers.connectors.municipal_overlays import (
    KNOWN_LAYERS,
    MunicipalOverlayClient,
    list_known_layers,
)
from scrapers.connectors.llm_extractor import LLMExtractor

# Downtown Boston/Cambridge bbox
BBOX = "-71.12,42.34,-71.04,42.38"
# A point in Beacon Hill
TEST_LAT, TEST_LON = 42.3588, -71.0650

DATA_CACHE_DIR = Path(__file__).parent.parent / "data_cache"


async def test_bbox_query(client: MunicipalOverlayClient, label: str) -> None:
    """Run a bbox query and print summary."""
    print(f"\n{'='*60}")
    print(f"  BBOX query — {label}")
    print(f"  bbox = {BBOX}")
    print(f"{'='*60}")

    result = await client.query_bbox(BBOX)

    if result is None:
        print("  ⚠  No result (request failed or ArcGIS error).")
        return

    features = result.get("features", [])
    print(f"  ✓  Returned {len(features)} feature(s)")

    if features:
        # Show first 3 features (properties + geometry type)
        for i, feat in enumerate(features[:3]):
            props = feat.get("properties", {})
            geom_type = (feat.get("geometry") or {}).get("type", "?")
            print(f"\n  ── Feature {i+1} ({geom_type}) ──")
            for k, v in props.items():
                print(f"     {k}: {v}")

        if len(features) > 3:
            print(f"\n  … and {len(features) - 3} more feature(s)")

    # Print raw GeoJSON (truncated for readability)
    raw = json.dumps(result, indent=2)
    if len(raw) > 2000:
        print(f"\n  Raw GeoJSON (first 2000 chars):\n{raw[:2000]}\n  … [truncated]")
    else:
        print(f"\n  Raw GeoJSON:\n{raw}")


async def test_point_query(client: MunicipalOverlayClient, label: str) -> None:
    """Run a point query and print summary."""
    print(f"\n{'='*60}")
    print(f"  POINT query — {label}")
    print(f"  lat={TEST_LAT}, lon={TEST_LON}")
    print(f"{'='*60}")

    result = await client.query_point(TEST_LAT, TEST_LON)

    if result is None:
        print("  ⚠  No result (request failed or ArcGIS error).")
        return

    features = result.get("features", [])
    print(f"  ✓  Returned {len(features)} feature(s)")

    if features:
        feat = features[0]
        props = feat.get("properties", {})
        geom_type = (feat.get("geometry") or {}).get("type", "?")
        print(f"\n  ── First Feature ({geom_type}) ──")
        for k, v in props.items():
            print(f"     {k}: {v}")


async def main() -> None:
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   Municipal Overlay Districts — Full Scrape Run         ║")
    print("╚══════════════════════════════════════════════════════════╝")

    os.makedirs(DATA_CACHE_DIR, exist_ok=True)
    list_layers = list_known_layers()

    print(f"\nDiscovered {len(list_layers)} overlay layers. Starting extraction...")

    for layer_info in list_layers:
        key = layer_info["key"]
        desc = layer_info["description"]
        url = KNOWN_LAYERS[key]["url"]
        
        print(f"\n============================================================")
        print(f"  Scraping Layer: {key}")
        print(f"  {desc}")
        print(f"============================================================")

        client = MunicipalOverlayClient(url)
        
        # 1. Fetch bbox data
        result = await client.query_bbox(BBOX)
        
        if result is None:
            print(f"  ⚠  Failed to fetch layer {key}.")
            continue
            
        features = result.get("features", [])
        print(f"  ✓  Fetched {len(features)} features for bbox {BBOX}")
        
        # 2. Save raw GeoJSON to disk
        out_path = DATA_CACHE_DIR / f"{key}.geojson"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  ✓  Saved to data_cache/{key}.geojson")

        # 3. LLM Enrichment
        if features:
            await llm_enrich(result, desc)

    print("\n✅  All scraping tasks completed.")


async def llm_enrich(geojson: "dict | None", layer_label: str) -> None:
    """Send overlay feature summaries to OpenRouter and print interpretation."""
    print(f"\n{'='*60}")
    print(f"  LLM Enrichment (OpenRouter) — {layer_label}")
    print(f"{'='*60}")

    if not geojson:
        print("  ⚠  No GeoJSON to enrich.")
        return

    features = geojson.get("features", [])
    if not features:
        print("  ⚠  Zero features in GeoJSON — nothing to enrich.")
        return

    # Build a compact summary of features to send to the LLM
    feature_summaries = []
    for i, feat in enumerate(features[:20]):  # cap at 20 to stay within token limits
        props = feat.get("properties", {})
        geom_type = (feat.get("geometry") or {}).get("type", "unknown")
        feature_summaries.append(f"Feature {i+1} ({geom_type}): {json.dumps(props)}")

    feature_text = "\n".join(feature_summaries)
    if len(features) > 20:
        feature_text += f"\n... and {len(features) - 20} more features."

    prompt = f"""You are a Massachusetts real estate and municipal planning analyst.

The following GeoJSON features were returned from the "{layer_label}" ArcGIS FeatureServer,
queried for a bounding box covering downtown Boston (Back Bay to Financial District).

Feature data:
{feature_text}

Please provide:
1. A 2-3 sentence plain-English summary of what these overlay features represent and where they are.
2. Why this overlay data matters for real estate developers and investors in Boston.
3. Any notable risks or opportunities implied by the data.

Return ONLY the plain text analysis (no JSON, no markdown headers)."""

    try:
        llm = LLMExtractor(provider="openrouter")
        print(f"  Using model: {llm.model}")
        print("  Calling OpenRouter...")
        response = llm._call_llm(prompt, max_tokens=600)
        print(f"\n  ── LLM Analysis ──\n")
        print(f"  {response.replace(chr(10), chr(10) + '  ')}")
    except Exception as exc:
        print(f"  ⚠  LLM enrichment failed: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
