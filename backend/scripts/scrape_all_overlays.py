"""Scrape zoning overlay data for all 12 MVP towns from MassGIS.

Phase 1b: Municipal Overlays — ArcGIS REST queries, no LLM needed.
Source: MassGIS L3 Parcel Assessors (USE_CODE land-use classifications)

The MassGIS Level-3 parcel dataset is the best publicly available statewide
proxy for zoning, providing assessor use codes (USE_CODE) per parcel polygon.
A single statewide municipal zoning-district polygon layer does not exist as
a free public endpoint; this is the canonical free alternative.

Usage:
    python -m backend.scripts.scrape_all_overlays
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.scrapers.connectors.massgis_zoning_overlay import MassGISZoningOverlayClient
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

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data_cache" / "overlays"


def _bbox_tuple(town_cfg):
    """Return (west, south, east, north) floats from TownConfig."""
    return (
        town_cfg.bbox_west,
        town_cfg.bbox_south,
        town_cfg.bbox_east,
        town_cfg.bbox_north,
    )


async def scrape_town(
    town_id: str,
    client: MassGISZoningOverlayClient,
) -> dict:
    """Fetch zoning overlay data for a single town."""
    cfg = TARGET_TOWNS.get(town_id)
    if not cfg:
        logger.warning("No config for town %s — skipping", town_id)
        return {"town": town_id, "error": "no config"}

    west, south, east, north = _bbox_tuple(cfg)
    logger.info(
        "Scraping %s  bbox=[%.3f,%.3f,%.3f,%.3f]",
        town_id, west, south, east, north,
    )

    result = await client.get_zoning_overlays(
        town_id=town_id,
        bbox_west=west,
        bbox_south=south,
        bbox_east=east,
        bbox_north=north,
    )

    # Attach display name for readability
    result["display_name"] = cfg.name

    summary_count = result.get("summary_count", 0)
    feature_count = result.get("feature_count", 0)
    error = result.get("error")

    if error:
        logger.warning("  %s => ERROR: %s", town_id, error)
    else:
        # Log top-5 use codes
        top = result.get("use_code_summary", [])[:5]
        top_str = ", ".join(
            f"{r['use_code']}({r['parcel_count']})" for r in top
        )
        logger.info(
            "  %s => %d use-code groups, %d parcel features | top: %s",
            town_id, summary_count, feature_count, top_str,
        )

    return result


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = MassGISZoningOverlayClient(timeout=45.0)
    summary_rows = []

    for town_id in MVP_TOWN_IDS:
        try:
            result = await scrape_town(town_id, client)
        except Exception as exc:
            logger.error("Failed %s: %s", town_id, exc, exc_info=True)
            result = {"town_id": town_id, "display_name": town_id, "error": str(exc)}

        # Save per-town JSON (strip large geometry to keep the file reasonable)
        out_path = OUTPUT_DIR / f"{town_id}_overlays.json"
        with open(out_path, "w") as fh:
            json.dump(result, fh, indent=2, default=str)

        size_kb = out_path.stat().st_size // 1024
        logger.info("  Saved %s (%d KB)", out_path.name, size_kb)

        summary_rows.append(
            {
                "town": town_id,
                "display_name": result.get("display_name", town_id),
                "use_code_groups": result.get("summary_count", 0),
                "parcel_features": result.get("feature_count", 0),
                "error": result.get("error"),
            }
        )

        # Brief pause between towns to be polite to MassGIS servers
        await asyncio.sleep(0.5)

    # ── Summary ─────────────────────────────────────────────────────────
    summary_path = OUTPUT_DIR / "_summary.json"
    with open(summary_path, "w") as fh:
        json.dump(summary_rows, fh, indent=2)

    logger.info("=" * 60)
    logger.info("ZONING OVERLAY SCRAPE COMPLETE")
    logger.info("=" * 60)

    total_groups = sum(r["use_code_groups"] for r in summary_rows)
    total_features = sum(r["parcel_features"] for r in summary_rows)
    errors = [r["town"] for r in summary_rows if r.get("error")]

    logger.info("Total USE_CODE groups across 12 towns : %d", total_groups)
    logger.info("Total parcel features (geo) returned  : %d", total_features)

    logger.info("")
    logger.info("%-12s  %-18s  %8s  %8s  %s",
                "Town", "Display Name", "Groups", "Features", "Error")
    logger.info("-" * 70)
    for r in summary_rows:
        logger.info(
            "%-12s  %-18s  %8d  %8d  %s",
            r["town"], r["display_name"],
            r["use_code_groups"], r["parcel_features"],
            r.get("error") or "OK",
        )

    if errors:
        logger.warning("Towns with errors: %s", errors)
    else:
        logger.info("All 12 towns scraped successfully!")


if __name__ == "__main__":
    asyncio.run(main())
