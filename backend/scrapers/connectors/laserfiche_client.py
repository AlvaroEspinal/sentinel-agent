import httpx
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

class LaserficheClient:
    def __init__(self, base_url="https://records.lexingtonma.gov/WebLink", repo_name="TownOfLexington"):
        self.base_url = base_url.rstrip("/")
        self.repo_name = repo_name
        self.client = httpx.AsyncClient(verify=False, follow_redirects=True, timeout=30.0)
        self.headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        }
        self.session_initialized = False

    async def _init_session(self):
        if not self.session_initialized:
            welcome_url = f"{self.base_url}/Welcome.aspx?dbid=0"
            await self.client.get(welcome_url)
            self.session_initialized = True

    async def get_folder_contents(self, folder_id):
        await self._init_session()
        url = f"{self.base_url}/FolderListingService.aspx/GetFolderListing2"
        
        all_entries = []
        start = 0
        total = 1
        
        while start < total:
            is_new = (start == 0)
            payload = {
                "repoName": self.repo_name,
                "folderId": folder_id,
                "getNewListing": is_new,
                "start": start,
                "end": start + 80,
                "sortColumn": "",
                "sortAscending": True
            }
            try:
                resp = await self.client.post(url, json=payload, headers=self.headers)
                resp.raise_for_status()
                json_data = resp.json()
            except Exception as e:
                logger.error(f"Error fetching Laserfiche folder {folder_id}: {e}")
                break
                
            inner_obj = json_data.get('d') or json_data.get('data') or {}
            total = inner_obj.get('totalEntries', 0)
            items = inner_obj.get('listing') or inner_obj.get('results') or []
            
            if not items:
                break
                
            for item in items:
                if isinstance(item, dict):
                    all_entries.append(item)
                    
            start += 80
            
        return all_entries

    async def get_recent_documents(self, root_folder_id: int, target_years: list[int]):
        """Traverse down from minutes root -> decade folder -> year folder -> documents.
           Lexington structure: root (2920639) -> '2020-2029' (492257) -> '2024' (492269) -> [pdf files]
        """
        all_docs = []
        
        # 1. Get decade folders
        level1 = await self.get_folder_contents(root_folder_id)
        for d_folder in level1:
            if d_folder.get('type') != 0:
                continue # not a folder
                
            name = d_folder.get('name', '')
            
            # Check if this decade folder could contain our target years
            # "2020-2029" -> check if any target_year string is inside it? No, just check if any target year starts with the first 3 chars "202"
            # Or just traverse all folders that look like years/decades
            should_traverse = False
            for y in target_years:
                if str(y) in name or str(y)[:3] in name:
                    should_traverse = True
            
            # If no years specified or it's not a strict decade format, just traverse it to be safe (max 1 level depth anyway)
            # Actually Lexington uses strictly "2020-2029" or "2024" etc.
            
            if not should_traverse and "20" in name:
                continue # skip old decades like 1990-1999
                
            # 2. Get year folders inside decade folder
            level2 = await self.get_folder_contents(d_folder.get('entryId'))
            for y_folder in level2:
                # Some might be direct documents!
                if y_folder.get('type') != 0:
                    y_name = y_folder.get('name', '')
                    if any(str(y) in y_name for y in target_years):
                       all_docs.append(y_folder)
                    continue
                    
                y_name = y_folder.get('name', '')
                if not any(str(y) in y_name for y in target_years):
                    continue # skip years we don't care about
                    
                # 3. Get documents inside this year folder
                level3 = await self.get_folder_contents(y_folder.get('entryId'))
                for doc in level3:
                    if doc.get('type') != 0:
                        all_docs.append(doc)
                        
        return all_docs

    def get_download_url(self, entry_id):
        return f"{self.base_url}/0/edoc/{entry_id}/document.pdf"
        
    @staticmethod
    def extract_pdf_text(pdf_bytes: bytes) -> str:
        import pdfplumber
        import io
        text = ""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
        return text

    async def download_pdf(self, url: str) -> Optional[bytes]:
        await self._init_session()
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error(f"Failed to download PDF {url}: {e}")
            return None

    async def close(self):
        await self.client.aclose()
