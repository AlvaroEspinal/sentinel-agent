"""
Target Town Configuration Registry — Affluent MA Towns

Central configuration for all scraping targets. Each town has:
- Geographic info (county, center lat/lon, registry district)
- Data source URLs (permit portal, meeting minutes, assessor, zoning)
- Portal type hints (socrata, viewpointcloud, firecrawl, none)
- Scrape schedule configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class BoardConfig:
    """Configuration for a municipal board's meeting minutes."""
    name: str                    # e.g. "Planning Board"
    slug: str                    # e.g. "planning_board"
    minutes_url: Optional[str] = None
    agendas_url: Optional[str] = None


@dataclass(frozen=True)
class TownConfig:
    """Full configuration for a target town."""
    id: str                      # lowercase slug: "newton"
    name: str                    # display name: "Newton"
    state: str = "MA"
    county: str = ""
    registry_district: str = ""  # "southern_middlesex", "norfolk", etc.

    # Geography
    center_lat: float = 0.0
    center_lon: float = 0.0
    # Rough bounding box for bulk MassGIS queries
    bbox_south: float = 0.0
    bbox_north: float = 0.0
    bbox_west: float = 0.0
    bbox_east: float = 0.0

    # Demographics
    population: int = 0
    median_home_value: int = 0

    # Data source URLs
    permit_portal_url: Optional[str] = None
    permit_portal_type: str = "unknown"  # socrata, viewpointcloud, firecrawl, none
    meeting_minutes_url: Optional[str] = None
    assessor_url: Optional[str] = None
    zoning_bylaw_url: Optional[str] = None
    gis_portal_url: Optional[str] = None

    # Socrata-specific (if permit_portal_type == "socrata")
    socrata_base_url: Optional[str] = None
    socrata_datasets: Dict[str, str] = field(default_factory=dict)

    # ViewpointCloud-specific (if permit_portal_type == "viewpointcloud")
    viewpointcloud_slug: Optional[str] = None

    # Boards for meeting minutes scraping
    boards: List[BoardConfig] = field(default_factory=list)

    # Scrape schedule (cron-like)
    permits_scrape_interval_hours: int = 168   # weekly
    minutes_scrape_interval_hours: int = 168   # weekly
    transfers_scrape_interval_hours: int = 24  # daily


# ── Default boards common to all MA towns ────────────────────────────────────

DEFAULT_BOARDS = [
    BoardConfig(
        name="Select Board",
        slug="select_board",
    ),
    BoardConfig(
        name="Planning Board",
        slug="planning_board",
    ),
    BoardConfig(
        name="Zoning Board of Appeals",
        slug="zba",
    ),
    BoardConfig(
        name="Conservation Commission",
        slug="conservation_commission",
    ),
]


# ── Target Towns ─────────────────────────────────────────────────────────────

TARGET_TOWNS: Dict[str, TownConfig] = {

    "newton": TownConfig(
        id="newton",
        name="Newton",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.337,
        center_lon=-71.209,
        bbox_south=42.285, bbox_north=42.370,
        bbox_west=-71.270, bbox_east=-71.155,
        population=88923,
        median_home_value=1_350_000,
        permit_portal_url="https://newtonma.viewpointcloud.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="newtonma",
        meeting_minutes_url="https://www.newtonma.gov/government/city-council/agendas-minutes",
        assessor_url="https://www.newtonma.gov/government/assessing",
        zoning_bylaw_url="https://ecode360.com/NE0839",
        gis_portal_url="https://www.newtonma.gov/government/information-technology/gis-maps",
        boards=[
            BoardConfig("City Council", "city_council",
                        minutes_url="https://www.newtonma.gov/government/city-council/agendas-minutes"),
            BoardConfig("Planning & Development Board", "planning_board",
                        minutes_url="https://www.newtonma.gov/government/planning/planning-development-board"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.newtonma.gov/government/planning/zoning-board-of-appeals"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.newtonma.gov/government/planning/conservation-commission"),
        ],
    ),

    "wellesley": TownConfig(
        id="wellesley",
        name="Wellesley",
        county="Norfolk",
        registry_district="norfolk",
        center_lat=42.297,
        center_lon=-71.292,
        bbox_south=42.270, bbox_north=42.325,
        bbox_west=-71.330, bbox_east=-71.250,
        population=29673,
        median_home_value=1_600_000,
        permit_portal_url="https://wellesleyma.viewpointcloud.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="wellesleyma",
        meeting_minutes_url="https://www.wellesleyma.gov/AgendaCenter",
        assessor_url="https://www.wellesleyma.gov/200/Board-of-Assessors",
        zoning_bylaw_url="https://ecode360.com/WE0397",
        boards=[
            BoardConfig("Board of Selectmen", "select_board",
                        minutes_url="https://www.wellesleyma.gov/AgendaCenter/Board-of-Selectmen-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.wellesleyma.gov/AgendaCenter/Planning-Board-12"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.wellesleyma.gov/AgendaCenter/Zoning-Board-of-Appeals-14"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.wellesleyma.gov/AgendaCenter/Conservation-Commission-5"),
        ],
    ),

    "weston": TownConfig(
        id="weston",
        name="Weston",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.367,
        center_lon=-71.303,
        bbox_south=42.335, bbox_north=42.400,
        bbox_west=-71.345, bbox_east=-71.260,
        population=12135,
        median_home_value=2_200_000,
        permit_portal_url="https://www.mapsonline.net/westonma/public_permit_reports.html.php",
        permit_portal_type="simplicity",
        meeting_minutes_url="https://www.westonma.gov/AgendaCenter",
        assessor_url="https://www.westonma.gov/107/Board-of-Assessors",
        zoning_bylaw_url="https://ecode360.com/WE0479",
        boards=[
            BoardConfig("Board of Selectmen", "select_board",
                        minutes_url="https://www.westonma.gov/AgendaCenter/Board-of-Selectmen-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.westonma.gov/AgendaCenter/Planning-Board-5"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.westonma.gov/AgendaCenter/Zoning-Board-of-Appeals-7"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.westonma.gov/AgendaCenter/Conservation-Commission-3"),
        ],
    ),

    "brookline": TownConfig(
        id="brookline",
        name="Brookline",
        county="Norfolk",
        registry_district="norfolk",
        center_lat=42.332,
        center_lon=-71.121,
        bbox_south=42.310, bbox_north=42.355,
        bbox_west=-71.180, bbox_east=-71.105,
        population=63191,
        median_home_value=1_200_000,
        permit_portal_url="https://brooklinema.portal.opengov.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="brooklinema",
        meeting_minutes_url="https://www.brooklinema.gov/AgendaCenter",
        assessor_url="https://www.brooklinema.gov/180/Board-of-Assessors",
        zoning_bylaw_url="https://ecode360.com/BR0778",
        boards=[
            BoardConfig("Select Board", "select_board",
                        minutes_url="https://www.brooklinema.gov/AgendaCenter/Select-Board-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.brooklinema.gov/AgendaCenter/Planning-Board-10"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.brooklinema.gov/AgendaCenter/Zoning-Board-of-Appeals-14"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.brooklinema.gov/AgendaCenter/Conservation-Commission-3"),
        ],
    ),

    "needham": TownConfig(
        id="needham",
        name="Needham",
        county="Norfolk",
        registry_district="norfolk",
        center_lat=42.280,
        center_lon=-71.233,
        bbox_south=42.255, bbox_north=42.310,
        bbox_west=-71.270, bbox_east=-71.195,
        population=31388,
        median_home_value=1_150_000,
        permit_portal_url="https://needhamma.portal.opengov.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="needhamma",
        meeting_minutes_url="https://www.needhamma.gov/AgendaCenter",
        assessor_url="https://www.needhamma.gov/163/Assessors-Office",
        zoning_bylaw_url="https://ecode360.com/NE0195",
        boards=[
            BoardConfig("Board of Selectmen", "select_board",
                        minutes_url="https://www.needhamma.gov/AgendaCenter/Board-of-Selectmen-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.needhamma.gov/AgendaCenter/Planning-Board-11"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.needhamma.gov/AgendaCenter/Conservation-Commission-4"),
        ],
    ),

    "dover": TownConfig(
        id="dover",
        name="Dover",
        county="Norfolk",
        registry_district="norfolk",
        center_lat=42.246,
        center_lon=-71.282,
        bbox_south=42.215, bbox_north=42.270,
        bbox_west=-71.320, bbox_east=-71.245,
        population=6215,
        median_home_value=1_800_000,
        permit_portal_url="https://doverma.portal.opengov.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="doverma",
        meeting_minutes_url="https://www.doverma.gov/AgendaCenter",
        assessor_url="https://www.doverma.gov/137/Board-of-Assessors",
        boards=[
            BoardConfig("Board of Selectmen", "select_board",
                        minutes_url="https://www.doverma.gov/AgendaCenter/Board-of-Selectmen-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.doverma.gov/AgendaCenter/Planning-Board-10"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission"),
        ],
    ),

    "sherborn": TownConfig(
        id="sherborn",
        name="Sherborn",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.238,
        center_lon=-71.369,
        bbox_south=42.210, bbox_north=42.265,
        bbox_west=-71.410, bbox_east=-71.330,
        population=4335,
        median_home_value=1_100_000,
        permit_portal_url="https://www.mapsonline.net/sherbornma/public_permit_reports.html.php",
        permit_portal_type="simplicity",
        meeting_minutes_url="https://www.sherbornma.org/agendas-minutes",
        boards=[
            BoardConfig("Board of Selectmen", "select_board"),
            BoardConfig("Planning Board", "planning_board"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission"),
        ],
    ),

    "natick": TownConfig(
        id="natick",
        name="Natick",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.283,
        center_lon=-71.349,
        bbox_south=42.260, bbox_north=42.310,
        bbox_west=-71.395, bbox_east=-71.310,
        population=36050,
        median_home_value=850_000,
        permit_portal_url="https://natickma.viewpointcloud.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="natickma",
        meeting_minutes_url="https://www.natickma.gov/AgendaCenter",
        assessor_url="https://www.natickma.gov/277/Board-of-Assessors",
        boards=[
            BoardConfig("Select Board", "select_board",
                        minutes_url="https://www.natickma.gov/AgendaCenter/Select-Board-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.natickma.gov/AgendaCenter/Planning-Board-10"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission"),
        ],
    ),

    "wayland": TownConfig(
        id="wayland",
        name="Wayland",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.363,
        center_lon=-71.361,
        bbox_south=42.335, bbox_north=42.395,
        bbox_west=-71.400, bbox_east=-71.320,
        population=13835,
        median_home_value=1_050_000,
        permit_portal_url="https://waylandma.viewpointcloud.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="waylandma",
        meeting_minutes_url="https://www.wayland.ma.us/agendas-minutes",
        boards=[
            BoardConfig("Board of Selectmen", "select_board"),
            BoardConfig("Planning Board", "planning_board"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission"),
        ],
    ),

    "lincoln": TownConfig(
        id="lincoln",
        name="Lincoln",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.426,
        center_lon=-71.305,
        bbox_south=42.400, bbox_north=42.455,
        bbox_west=-71.350, bbox_east=-71.265,
        population=7012,
        median_home_value=1_400_000,
        permit_portal_url="https://permiteyes.us/lincoln/publicview.php",
        permit_portal_type="permiteyes",
        meeting_minutes_url="https://www.lincolntown.org/AgendaCenter",
        boards=[
            BoardConfig("Board of Selectmen", "select_board"),
            BoardConfig("Planning Board", "planning_board"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission"),
        ],
    ),

    "concord": TownConfig(
        id="concord",
        name="Concord",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.460,
        center_lon=-71.349,
        bbox_south=42.425, bbox_north=42.495,
        bbox_west=-71.400, bbox_east=-71.300,
        population=19872,
        median_home_value=1_250_000,
        permit_portal_url="https://permiteyes.us/concord/publicview.php",
        permit_portal_type="permiteyes",
        meeting_minutes_url="https://concordma.gov/AgendaCenter",
        assessor_url="https://concordma.gov/285/Board-of-Assessors",
        zoning_bylaw_url="https://ecode360.com/CO0735",
        boards=[
            BoardConfig("Select Board", "select_board",
                        minutes_url="https://concordma.gov/AgendaCenter/Select-Board-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://concordma.gov/AgendaCenter/Planning-Board-7"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission"),
        ],
    ),

    "lexington": TownConfig(
        id="lexington",
        name="Lexington",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.443,
        center_lon=-71.226,
        bbox_south=42.415, bbox_north=42.475,
        bbox_west=-71.260, bbox_east=-71.190,
        population=34454,
        median_home_value=1_300_000,
        permit_portal_url="https://lexingtonma.viewpointcloud.com",
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="lexingtonma",
        meeting_minutes_url="https://www.lexingtonma.gov/AgendaCenter",
        assessor_url="https://www.lexingtonma.gov/assessors-office",
        zoning_bylaw_url="https://ecode360.com/LE0741",
        boards=[
            BoardConfig("Select Board", "select_board",
                        minutes_url="https://www.lexingtonma.gov/AgendaCenter/Select-Board-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.lexingtonma.gov/AgendaCenter/Planning-Board-12"),
            BoardConfig("Zoning Board of Appeals", "zba"),
            BoardConfig("Conservation Commission", "conservation_commission"),
        ],
    ),
    # ── Socrata Towns ──────────────────────────────────────────────────────

    "cambridge": TownConfig(
        id="cambridge",
        name="Cambridge",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.374,
        center_lon=-71.106,
        population=118403,
        median_home_value=1_800_000,
        permit_portal_type="socrata",
        socrata_base_url="https://data.cambridgema.gov",
        socrata_datasets={
            "new_construction": "9qm7-wbdc",
            "addition_alteration": "qu2z-8suj",
            "electrical": "hvtc-3ab9",
            "plumbing": "8793-tet2",
            "gas": "5cra-jws5",
            "mechanical": "4rb4-q8tj",
            "demolition": "kcfi-ackv",
            "solar": "whpw-w55x",
            "roof": "79ih-g44d",
            "siding": "ddej-349p",
        },
    ),

    "somerville": TownConfig(
        id="somerville",
        name="Somerville",
        county="Middlesex",
        registry_district="southern_middlesex",
        center_lat=42.388,
        center_lon=-71.100,
        population=81360,
        median_home_value=950_000,
        permit_portal_type="socrata",
        socrata_base_url="https://data.somervillema.gov",
        socrata_datasets={
            "permits": "vxgw-vmky",
        },
    ),

    # ── Additional PermitEyes Towns ──────────────────────────────────────

    "chicopee": TownConfig(
        id="chicopee",
        name="Chicopee",
        county="Hampden",
        center_lat=42.149,
        center_lon=-72.607,
        population=55298,
        median_home_value=250_000,
        permit_portal_url="https://permiteyes.us/chicopee/publicview.php",
        permit_portal_type="permiteyes",
    ),

    "easthampton": TownConfig(
        id="easthampton",
        name="Easthampton",
        county="Hampshire",
        center_lat=42.267,
        center_lon=-72.669,
        population=16053,
        median_home_value=340_000,
        permit_portal_url="https://permiteyes.us/easthampton/publicview.php",
        permit_portal_type="permiteyes",
    ),

    "taunton": TownConfig(
        id="taunton",
        name="Taunton",
        county="Bristol",
        center_lat=41.901,
        center_lon=-71.094,
        population=57464,
        median_home_value=380_000,
        permit_portal_url="https://permiteyes.us/taunton/publicview.php",
        permit_portal_type="permiteyes",
    ),

    "west_bridgewater": TownConfig(
        id="west_bridgewater",
        name="West Bridgewater",
        county="Plymouth",
        center_lat=42.019,
        center_lon=-71.008,
        population=7606,
        median_home_value=420_000,
        permit_portal_url="https://permiteyes.us/westbridgewater/publicview.php",
        permit_portal_type="permiteyes",
    ),
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_town(town_id: str) -> Optional[TownConfig]:
    """Get a town config by ID (case-insensitive)."""
    return TARGET_TOWNS.get(town_id.lower())


def get_all_towns() -> Dict[str, TownConfig]:
    """Return all target town configs."""
    return TARGET_TOWNS


def get_town_ids() -> List[str]:
    """Return list of all target town IDs."""
    return list(TARGET_TOWNS.keys())


def get_towns_by_county(county: str) -> List[TownConfig]:
    """Return towns in a specific county."""
    return [t for t in TARGET_TOWNS.values() if t.county.lower() == county.lower()]


def get_towns_by_registry(district: str) -> List[TownConfig]:
    """Return towns in a specific registry district."""
    return [t for t in TARGET_TOWNS.values()
            if t.registry_district.lower() == district.lower()]
