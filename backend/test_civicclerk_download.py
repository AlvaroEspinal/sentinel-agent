import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        url = "https://brooklinema.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=28161,plainText=false)"
        resp = await client.get(url, follow_redirects=True)
        print(resp.status_code)
        print(resp.headers)
        if resp.status_code == 200:
            print("Content start:", resp.content[:50])
asyncio.run(test())
