import asyncio
import httpx
from pprint import pprint

async def main():
    bbox = "-71.30,42.3,-71.20,42.4"
    
    # Test Wetlands
    from scrapers.connectors.massgis_wetlands import MassGISWetlandsClient
    print(f"Testing wetlands query for bbox: {bbox}")
    wet_client = MassGISWetlandsClient()
    wet_res = await wet_client.get_wetlands_in_bbox(bbox)
    if wet_res and "features" in wet_res:
        print(f"Wetlands Success! Found {len(wet_res['features'])} features.")
        if wet_res['features']:
            print("Sample feature keys:", wet_res['features'][0].keys())
    else:
        print("Wetlands Error:", wet_res)
        
    print("-" * 40)
    
    # Test Conservation
    from scrapers.connectors.massgis_openspace import MassGISOpenSpaceClient
    print(f"Testing conservation query for bbox: {bbox}")
    os_client = MassGISOpenSpaceClient()
    os_res = await os_client.get_openspace_in_bbox(bbox)
    if os_res and "features" in os_res:
        print(f"Conservation Success! Found {len(os_res['features'])} features.")
        if os_res['features']:
            print("Sample feature props:", os_res['features'][0].get("properties", {}))
    else:
        print("Conservation Error:", os_res)

if __name__ == "__main__":
    asyncio.run(main())
