from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # The portal URL with the stream path
        url = "https://brooklinema.portal.civicclerk.com/stream/BROOKLINEMA/4d856564-ae28-4cfc-a077-19388654909c.pdf"
        print("Navigating to", url)
        
        # We need to see if it downloads or renders. 
        # By default playwright navigates. If it's a download, it triggers download event.
        # But if it's an SPA, it might render a PDF viewer.
        page.goto(url, wait_until="networkidle")
        print("Page title:", page.title())
        print("Page content length:", len(page.content()))
        
        # Let's see if there's an iframe or pdf embed
        frames = page.frames
        print("Frames:", len(frames))
        browser.close()

if __name__ == "__main__":
    test()
