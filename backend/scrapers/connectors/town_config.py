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
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.doverma.gov/AgendaCenter/Board-of-Appeals-4"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.doverma.gov/AgendaCenter/Conservation-Commission-12"),
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
            BoardConfig("Board of Selectmen", "select_board",
                        minutes_url="https://www.sherbornma.org/AgendaCenter/Select-Board-5"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.sherbornma.org/AgendaCenter/Planning-Board-6"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.sherbornma.org/AgendaCenter/Zoning-Board-of-Appeals-28"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.sherbornma.org/AgendaCenter/Conservation-Commission-16"),
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
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.natickma.gov/AgendaCenter/Zoning-Board-of-Appeals-81"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.natickma.gov/AgendaCenter/Conservation-Commission-18"),
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
            BoardConfig("Board of Selectmen", "select_board",
                        minutes_url="https://www.wayland.ma.us/node/350/minutes"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.wayland.ma.us/node/36/minutes"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.wayland.ma.us/node/230/minutes"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.wayland.ma.us/node/240/minutes"),
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
            BoardConfig("Board of Selectmen", "select_board",
                        minutes_url="https://www.lincolntown.org/AgendaCenter/Select-Board-1"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://www.lincolntown.org/AgendaCenter/Planning-Board-22"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://www.lincolntown.org/AgendaCenter/Zoning-Board-of-Appeals-3"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://www.lincolntown.org/AgendaCenter/Conservation-Commission-13"),
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
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://concordma.gov/AgendaCenter/Zoning-Board-of-Appeals-45"),
            BoardConfig("Natural Resources Commission", "conservation_commission",
                        minutes_url="https://concordma.gov/AgendaCenter/Natural-Resources-Commission-41"),
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
                        minutes_url="https://records.lexingtonma.gov/WebLink/Browse.aspx?dbid=0&startid=2920639"),
            BoardConfig("Planning Board", "planning_board",
                        minutes_url="https://records.lexingtonma.gov/WebLink/Browse.aspx?dbid=0&startid=2920625"),
            BoardConfig("Zoning Board of Appeals", "zba",
                        minutes_url="https://records.lexingtonma.gov/WebLink/Browse.aspx?dbid=0&startid=2920512"),
            BoardConfig("Conservation Commission", "conservation_commission",
                        minutes_url="https://records.lexingtonma.gov/WebLink/Browse.aspx?dbid=0&startid=2920521"),
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
    # ── Discovered ViewpointCloud Towns (31 towns) ─────────────────────────

    "haverhill": TownConfig(
        id="haverhill",
        name="Haverhill",
        county="Essex",
        center_lat=42.776, center_lon=-71.077,
        population=67838,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="haverhillma",
    ),

    "shrewsbury": TownConfig(
        id="shrewsbury",
        name="Shrewsbury",
        county="Worcester",
        center_lat=42.296, center_lon=-71.713,
        population=38326,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="shrewsburyma",
    ),

    "acton": TownConfig(
        id="acton",
        name="Acton",
        county="Middlesex",
        center_lat=42.485, center_lon=-71.433,
        population=24194,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="actonma",
    ),

    "bourne": TownConfig(
        id="bourne",
        name="Bourne",
        county="Barnstable",
        center_lat=41.741, center_lon=-70.599,
        population=19865,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="bournema",
    ),

    "framingham": TownConfig(
        id="framingham",
        name="Framingham",
        county="Middlesex",
        center_lat=42.280, center_lon=-71.417,
        population=72032,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="framinghamma",
    ),

    "salem": TownConfig(
        id="salem",
        name="Salem",
        county="Essex",
        center_lat=42.520, center_lon=-70.897,
        population=44480,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="salemma",
    ),

    "franklin": TownConfig(
        id="franklin",
        name="Franklin",
        county="Norfolk",
        center_lat=42.083, center_lon=-71.397,
        population=34087,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="franklinma",
    ),

    "walpole": TownConfig(
        id="walpole",
        name="Walpole",
        county="Norfolk",
        center_lat=42.142, center_lon=-71.250,
        population=25575,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="walpolema",
    ),

    "belmont": TownConfig(
        id="belmont",
        name="Belmont",
        county="Middlesex",
        center_lat=42.396, center_lon=-71.179,
        population=27295,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="belmontma",
    ),

    "barnstable": TownConfig(
        id="barnstable",
        name="Barnstable",
        county="Barnstable",
        center_lat=41.700, center_lon=-70.300,
        population=44641,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="barnstablema",
    ),

    "gloucester": TownConfig(
        id="gloucester",
        name="Gloucester",
        county="Essex",
        center_lat=42.615, center_lon=-70.662,
        population=30273,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="gloucesterma",
    ),

    "wrentham": TownConfig(
        id="wrentham",
        name="Wrentham",
        county="Norfolk",
        center_lat=42.066, center_lon=-71.329,
        population=12462,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="wrenthamma",
    ),

    "tewksbury": TownConfig(
        id="tewksbury",
        name="Tewksbury",
        county="Middlesex",
        center_lat=42.611, center_lon=-71.234,
        population=31668,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="tewksburyma",
    ),

    "tisbury": TownConfig(
        id="tisbury",
        name="Tisbury",
        county="Dukes",
        center_lat=41.457, center_lon=-70.604,
        population=4185,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="tisburyma",
    ),

    "dedham": TownConfig(
        id="dedham",
        name="Dedham",
        county="Norfolk",
        center_lat=42.242, center_lon=-71.163,
        population=25330,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="dedhamma",
    ),

    "quincy": TownConfig(
        id="quincy",
        name="Quincy",
        county="Norfolk",
        center_lat=42.251, center_lon=-71.002,
        population=101636,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="quincyma",
    ),

    "gardner": TownConfig(
        id="gardner",
        name="Gardner",
        county="Worcester",
        center_lat=42.575, center_lon=-71.998,
        population=21327,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="gardnerma",
    ),

    "orleans": TownConfig(
        id="orleans",
        name="Orleans",
        county="Barnstable",
        center_lat=41.789, center_lon=-69.990,
        population=5985,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="orleansma",
    ),

    "new_bedford": TownConfig(
        id="new_bedford",
        name="New Bedford",
        county="Bristol",
        center_lat=41.636, center_lon=-70.934,
        population=101079,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="newbedfordma",
    ),

    "hanover": TownConfig(
        id="hanover",
        name="Hanover",
        county="Plymouth",
        center_lat=42.113, center_lon=-70.812,
        population=14852,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="hanoverma",
    ),

    "rutland": TownConfig(
        id="rutland",
        name="Rutland",
        county="Worcester",
        center_lat=42.373, center_lon=-71.949,
        population=9295,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="rutlandma",
    ),

    "ashland": TownConfig(
        id="ashland",
        name="Ashland",
        county="Middlesex",
        center_lat=42.261, center_lon=-71.463,
        population=18165,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="ashlandma",
    ),

    "brewster": TownConfig(
        id="brewster",
        name="Brewster",
        county="Barnstable",
        center_lat=41.760, center_lon=-70.082,
        population=10318,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="brewsterma",
    ),

    "medfield": TownConfig(
        id="medfield",
        name="Medfield",
        county="Norfolk",
        center_lat=42.187, center_lon=-71.307,
        population=12841,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="medfieldma",
    ),

    "eastham": TownConfig(
        id="eastham",
        name="Eastham",
        county="Barnstable",
        center_lat=41.830, center_lon=-69.974,
        population=5188,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="easthamma",
    ),

    "marblehead": TownConfig(
        id="marblehead",
        name="Marblehead",
        county="Essex",
        center_lat=42.500, center_lon=-70.858,
        population=20667,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="marbleheadma",
    ),

    "manchester": TownConfig(
        id="manchester",
        name="Manchester-by-the-Sea",
        county="Essex",
        center_lat=42.578, center_lon=-70.770,
        population=5764,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="manchesterma",
    ),

    "peabody": TownConfig(
        id="peabody",
        name="Peabody",
        county="Essex",
        center_lat=42.528, center_lon=-70.929,
        population=54070,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="peabodyma",
    ),

    "sudbury": TownConfig(
        id="sudbury",
        name="Sudbury",
        county="Middlesex",
        center_lat=42.383, center_lon=-71.416,
        population=19655,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="sudburyma",
    ),

    "auburn": TownConfig(
        id="auburn",
        name="Auburn",
        county="Worcester",
        center_lat=42.195, center_lon=-71.846,
        population=16851,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="auburnma",
    ),

    "winchester": TownConfig(
        id="winchester",
        name="Winchester",
        county="Middlesex",
        center_lat=42.452, center_lon=-71.137,
        population=22970,
        median_home_value=1_200_000,
        permit_portal_type="viewpointcloud",
        viewpointcloud_slug="winchesterma",
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
