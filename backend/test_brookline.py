import httpx
from rich import print
resp = httpx.get("https://BrooklineMA.api.civicclerk.com/v1/Events?$orderby=eventDate%20desc&$top=5")
print(resp.json())
