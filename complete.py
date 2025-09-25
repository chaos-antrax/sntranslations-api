# run with
# .\venv\Scripts\Activate
# uvicorn ex-nov-dtl-api:app --host 0.0.0.0 --port 8000 --reload

from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
from pydantic import BaseModel
from openai import OpenAI
from typing import Dict, Any
import time
import uvicorn
import json
import os
import re

app = FastAPI()

# get novel details
def get_novel_details(page, base_url):
    """Extract novel details from the main book page"""
    try:
        page.wait_for_selector('div.bookbox', timeout=10000)
        bookbox = page.query_selector('div.bookbox')

        if bookbox:
            # Cover
            cover_img = bookbox.query_selector('div.bookimg2 img')
            cover_url = cover_img.get_attribute('src') if cover_img else None
            if cover_url and not cover_url.startswith('http'):
                cover_url = urljoin(base_url, cover_url)

            # Title
            title_element = bookbox.query_selector('div.booknav2 h1 a')
            title = title_element.text_content().strip() if title_element else None

            # Author
            author_element = bookbox.query_selector('div.booknav2 p:has-text("作者：") a')
            author = author_element.text_content().strip() if author_element else None
            if not author:
                author_p = bookbox.query_selector('div.booknav2 p:has-text("作者：")')
                if author_p:
                    author_text = author_p.text_content().strip()
                    author = author_text.replace('作者：', '').strip()

            return {
                'title': title,
                'author': author,
                'coverImg': cover_url
            }
        return None
    except Exception as e:
        print(f"Error extracting novel details: {e}")
        return None

# get chapters list
def crawl_chapters(page, index_url):
    """Crawl chapters from the index page"""
    chapters_data = []
    try:
        page.goto(index_url, wait_until='domcontentloaded')
        page.wait_for_selector('div.catalog', timeout=10000)
        catalog_div = page.query_selector('div.catalog:has(h3:has-text("目錄"))')

        if catalog_div:
            allchapter_div = catalog_div.query_selector('div#allchapter')
            if allchapter_div:
                load_more_button = allchapter_div.query_selector('a#loadmore.btn.more-btn')
                if load_more_button:
                    load_more_button.click()
                    page.wait_for_timeout(2000)

                chapter_items = allchapter_div.query_selector_all('li[data-num]')
                for item in chapter_items:
                    anchor = item.query_selector('a')
                    if anchor:
                        chapter_name = anchor.text_content().strip()
                        href = anchor.get_attribute('href')
                        chapter_num = item.get_attribute('data-num')
                        if href and not href.startswith('http'):
                            href = urljoin(index_url, href)
                        chapters_data.append({
                            'chapter_number': chapter_num,
                            'chapter_name': chapter_name,
                            'url': href
                        })
                return chapters_data
        return None
    except Exception as e:
        print(f"Error crawling chapters: {e}")
        return None

# get single chapter content
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

# translator
# -----------------------------
# CONFIG
# -----------------------------
OPENROUTER_API_KEY = "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"
TRANSLATION_FOLDER = "translations"
GLOSSARY_FILE = os.path.join(TRANSLATION_FOLDER, "glossary.json")

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def load_glossary() -> Dict[str, str]:
    """Load glossary from JSON file, create if it doesn't exist."""
    os.makedirs(TRANSLATION_FOLDER, exist_ok=True)

    if os.path.exists(GLOSSARY_FILE):
        try:
            with open(GLOSSARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print("Glossary file corrupted. Reinitializing.")
            with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            return {}
    else:
        with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        return {}

def save_glossary(glossary: Dict[str, str]):
    """Save glossary back to file."""
    os.makedirs(TRANSLATION_FOLDER, exist_ok=True)
    with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)

def translate_text_openrouter(text: str, glossary: Dict[str, str]):
    """Translate Chinese text to English using OpenRouter + DeepSeek."""
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

    # glossary context
    glossary_context = ""
    if glossary:
        glossary_context = "Use the following glossary for proper nouns:\n"
        for chinese, english in glossary.items():
            glossary_context += f"{chinese} -> {english}\n"
        glossary_context += "\n"

    # system prompt
    system_prompt = """You are a professional translator from Chinese to English.
    Follow these rules:
    1. Translate the text naturally while preserving the original meaning.
    2. For proper nouns (names, places, items, etc.), use the provided glossary if available.
    3. If you encounter a Chinese proper noun not in the glossary, add it to the new terms list.
    4. Format your response EXACTLY as follows:
    TRANSLATION: [your translation text here. The first line in the translation should be the chapter number and title if available.]
    NEW TERMS: [chinese:english, chinese:english, chinese:english]

    Each term should be on a separate line in the NEW TERMS section.
    Only include one term per line in the format "chinese:english"."""

    user_prompt = f"{glossary_context}Translate the following text:\n\n{text}"

    response = client.chat.completions.create(
        # model="deepseek/deepseek-chat-v3.1:free",
        model="x-ai/grok-4-fast:free",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    response_text = response.choices[0].message.content

    # extract translation and terms
    translation_match = re.search(
        r"TRANSLATION:\s*(.*?)(?=NEW TERMS:|$)", response_text, re.DOTALL
    )
    new_terms_match = re.search(r"NEW TERMS:\s*([\s\S]*)", response_text)

    translation = (
        translation_match.group(1).strip() if translation_match else response_text
    )
    new_terms: Dict[str, str] = {}

    if new_terms_match:
        for line in new_terms_match.group(1).splitlines():
            line = line.strip()
            if line and ":" in line:
                chinese, english = map(str.strip, line.split(":", 1))
                if chinese and english:
                    new_terms[chinese] = english

    return translation, new_terms

class TranslateRequest(BaseModel):
    text: str

# routes
@app.get("/scrape")
def scrape(url: str = Query(..., description="Novel URL (e.g., https://twkan.com/book/79291)")):
    url = url.rstrip('/')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless for API
        page = browser.new_page()
        try:
            page.goto(url, wait_until='domcontentloaded')
            novel_details = get_novel_details(page, url)
            if not novel_details:
                return JSONResponse(content={"error": "Failed to extract novel details"}, status_code=400)

            clean_base_url = url[:-5] if url.endswith('.html') else url
            index_url = clean_base_url + "/index.html"
            chapters = crawl_chapters(page, index_url)

            if not chapters:
                return JSONResponse(content={"error": "Failed to crawl chapters"}, status_code=400)

            result = {
                'title': novel_details['title'],
                'author': novel_details['author'],
                'coverImg': novel_details['coverImg'],
                'chapters': chapters
            }

            return JSONResponse(content=result, status_code=200)

        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)
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
    
@app.post("/translate")
def translate_endpoint(payload: TranslateRequest = Body(...)) -> Dict[str, Any]:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    glossary = load_glossary()
    translation, new_terms = translate_text_openrouter(text, glossary)

    # update glossary with new terms
    added = 0
    for chinese, english in new_terms.items():
        if chinese not in glossary:
            glossary[chinese] = english
            added += 1
    if added > 0:
        save_glossary(glossary)

    return {
        "translation": translation,
        "new_terms": new_terms,
        "glossary": glossary,
    }