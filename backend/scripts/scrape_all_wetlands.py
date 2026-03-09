"""Scrape wetlands & conservation data for all 12 MVP towns from MassGIS.

Phase 1a: Quick win — pure ArcGIS REST queries, no LLM needed.
Sources:
  - DEP Freshwater Wetlands (MassGISWetlandsClient)
  - Public Conservation Lands (MassGISOpenSpaceClient)

Usage:
    python -m backend.scripts.scrape_all_wetlands
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.scrapers.connectors.massgis_wetlands import MassGISWetlandsClient
from backend.scrapers.connectors.massgis_openspace import MassGISOpenSpaceClient
from backend.scrapers.connectors.town_config import TARGET_TOWNS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MVP_TOWN_IDS = [
    "newton", "wellesley", "weston", "brookline", "needham",
    "dover", "sherborn", "natick", "wayland", "lincoln",
    "concord", "lexington",
]

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "wetlands"


def _bbox_str(town_cfg) -> str:
    """Format town bbox as 'west,south,east,north' for ArcGIS envelope query."""
    return f"{town_cfg.bbox_west},{town_cfg.bbox_south},{town_cfg.bbox_east},{town_cfg.bbox_north}"


async def scrape_town(town_id: str, wetlands_client, openspace_client) -> dict:
    """Scrape wetlands + open-space data for a single town."""
    cfg = TARGET_TOWNS.get(town_id)
    if not cfg:
        logger.warning("No config for town %s — skipping", town_id)
        return {"town": town_id, "error": "no config"}

    bbox = _bbox_str(cfg)
    logger.info("Scraping %s  bbox=%s", town_id, bbox)

    wetlands_data = await wetlands_client.get_wetlands_in_bbox(bbox)
    openspace_data = await openspace_client.get_openspace_in_bbox(bbox)

    wetlands_count = len(wetlands_data.get("features", [])) if wetlands_data else 0
    openspace_count = len(openspace_data.get("features", [])) if openspace_data else 0

    logger.info(
        "  %s => wetlands=%d features, openspace=%d features",
        town_id, wetlands_count, openspace_count,
    )

    return {
        "town": town_id,
        "display_name": cfg.name,
        "bbox": bbox,
        "wetlands": wetlands_data,
        "wetlands_count": wetlands_count,
        "openspace": openspace_data,
        "openspace_count": openspace_count,
    }


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    wetlands_client = MassGISWetlandsClient()
    openspace_client = MassGISOpenSpaceClient()

    summary = []

    for town_id in MVP_TOWN_IDS:
        try:
            result = await scrape_town(town_id, wetlands_client, openspace_client)
        except Exception as exc:
            logger.error("Failed %s: %s", town_id, exc)
            result = {"town": town_id, "error": str(exc)}

        # Save per-town JSON
        out_path = OUTPUT_DIR / f"{town_id}_wetlands.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info("  Saved %s (%d bytes)", out_path.name, out_path.stat().st_size)

        summary.append({
            "town": town_id,
            "wetlands_features": result.get("wetlands_count", 0),
            "openspace_features": result.get("openspace_count", 0),
            "error": result.get("error"),
        })

        # Small delay to be polite to MassGIS servers
        await asyncio.sleep(0.5)

    # Save summary
    summary_path = OUTPUT_DIR / "_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("=" * 60)
    logger.info("WETLANDS/CONSERVATION SCRAPE COMPLETE")
    logger.info("=" * 60)
    total_w = sum(s["wetlands_features"] for s in summary)
    total_o = sum(s["openspace_features"] for s in summary)
    errors = [s["town"] for s in summary if s.get("error")]
    logger.info("Total wetland features: %d", total_w)
    logger.info("Total open-space features: %d", total_o)
    if errors:
        logger.warning("Towns with errors: %s", errors)
    else:
        logger.info("All 12 towns scraped successfully!")


if __name__ == "__main__":
    asyncio.run(main())
