# run with
# .\venv\Scripts\Activate
# uvicorn ex-sin-ch-api:app --host 0.0.0.0 --port 8000 --reload


from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import uvicorn
from playwright.sync_api import sync_playwright
import time

app = FastAPI(title="Chapter Extractor API")

def extract_single_chapter(chapter_url: str, headless: bool = True):
    """Enhanced chapter content extraction with stealth features"""
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=VizDisplayCompositor',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-component-extensions-with-background-pages',
                '--disable-default-apps',
                '--disable-extensions',
                '--disable-translate',
                '--disable-features=TranslateUI',
                '--mute-audio',
                '--window-size=1920,1080'
            ] if headless else []
        )

        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        ) if headless else browser.new_context()

        page = context.new_page()

        if headless:
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW', 'zh', 'en-US', 'en']});
                delete navigator.__proto__.webdriver;
            """)

        try:
            page.goto(chapter_url, wait_until='domcontentloaded', timeout=45000 if headless else 30000)
            time.sleep(2 if headless else 0)

            content_element = None
            try:
                content_element = page.wait_for_selector('div#txtcontent', timeout=8000)
            except:
                selectors = [
                    '#txtcontent', '.content', '.chapter-content',
                    '.txt-content', '[class*="content"]', '[id*="content"]'
                ]
                for sel in selectors:
                    el = page.query_selector(sel)
                    if el:
                        content_element = el
                        break

            if not content_element:
                return None

            content_html = content_element.inner_html()
            text = content_html.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
            while '<' in text and '>' in text:
                start = text.find('<')
                end = text.find('>', start)
                if end != -1:
                    text = text[:start] + text[end+1:]
                else:
                    break

            lines = [line.strip() for line in text.split('\n') if line.strip()]
            clean_content = '\n'.join(lines)

            return clean_content if len(clean_content) > 50 else None
        finally:
            browser.close()


@app.get("/extract")
def extract(url: str = Query(..., description="Chapter URL"), headless: bool = True):
    """Extract chapter content from a given URL"""
    try:
        content = extract_single_chapter(url, headless=headless)
        if content:
            return JSONResponse(content={"success": True, "content": content})
        else:
            return JSONResponse(content={"success": False, "error": "Failed to extract content"}, status_code=400)
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
