# run with
# .\venv\Scripts\Activate
# uvicorn ex-nov-dtl-api:app --host 0.0.0.0 --port 8000 --reload

import logging
from fastapi import FastAPI, Query, Body, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
from pydantic import BaseModel
from openai import OpenAI
from typing import Dict, Any, Optional
from pymongo import MongoClient
from bson import ObjectId
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
MONGODB_URI = "mongodb+srv://hasithajagoda2410:pUHv7Is76JI5s5HF@cluster0.9jl4qec.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# Initialize MongoDB client
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client["novel-reader"]


# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def get_novel_glossary(novel_id: str) -> Dict[str, str]:
    """Get glossary for a specific novel from MongoDB."""
    try:
        novel = db.novels.find_one({"_id": ObjectId(novel_id)})
        if novel and "glossary" in novel:
            return novel["glossary"]
        return {}
    except Exception as e:
        print(f"Error fetching glossary for novel {novel_id}: {e}")
        return {}

def update_novel_glossary(novel_id: str, new_terms: Dict[str, str]) -> bool:
    """Update novel's glossary with new terms in MongoDB."""
    try:
        # Get current glossary
        current_glossary = get_novel_glossary(novel_id)
        
        # Merge with new terms (new terms take precedence)
        updated_glossary = {**current_glossary, **new_terms}
        
        # Update in database
        result = db.novels.update_one(
            {"_id": ObjectId(novel_id)},
            {"$set": {"glossary": updated_glossary}}
        )
        
        return result.modified_count > 0
    except Exception as e:
        print(f"Error updating glossary for novel {novel_id}: {e}")
        return False

def translate_text_openrouter(text: str, chapter_name: str, glossary: Dict[str, str]):
    """Translate Chinese text and chapter name to English using OpenRouter + DeepSeek."""
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
    1. Translate both the chapter title and content naturally while preserving the original meaning.
    2. For proper nouns (names, places, items, etc.), use the provided glossary if available.
    3. If you encounter a Chinese proper noun or name of certain cultivation realms not in the glossary, add it to the new terms list.
    4. Format your response EXACTLY as follows:
    CHAPTER_TITLE: [translated chapter title here]
    TRANSLATION: [your translation text here]
    NEW_TERMS: [chinese:english, chinese:english, chinese:english]

    Each term should be on a separate line in the NEW_TERMS section.
    Only include one term per line in the format "chinese:english"."""

    user_prompt = f"""{glossary_context}Chapter Title: {chapter_name}

Chapter Content:
{text}

Please translate both the chapter title and content."""

    response = client.chat.completions.create(
        model="x-ai/grok-4-fast:free",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    response_text = response.choices[0].message.content

    # extract chapter title, translation and terms
    chapter_title_match = re.search(
        r"CHAPTER_TITLE:\s*(.*?)(?=TRANSLATION:|$)", response_text, re.DOTALL
    )
    translation_match = re.search(
        r"TRANSLATION:\s*(.*?)(?=NEW_TERMS:|$)", response_text, re.DOTALL
    )
    new_terms_match = re.search(r"NEW_TERMS:\s*([\s\S]*)", response_text)

    chapter_title = (
        chapter_title_match.group(1).strip() if chapter_title_match else chapter_name
    )
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

    return chapter_title, translation, new_terms

class TranslateRequest(BaseModel):
    text: str
    chapter_name: str
    novel_id: str




# configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# routes
@app.get("/scrape")
def scrape(url: str = Query(..., description="Novel URL (e.g., https://twkan.com/book/79291)")):
    logging.info(f"[SCRAPE] Started scraping for URL: {url}")
    url = url.rstrip('/')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless for API
        page = browser.new_page()
        try:
            page.goto(url, wait_until='domcontentloaded')
            novel_details = get_novel_details(page, url)
            if not novel_details:
                logging.info(f"[SCRAPE] Failed for URL: {url}")
                return JSONResponse(content={"error": "Failed to extract novel details"}, status_code=400)

            clean_base_url = url[:-5] if url.endswith('.html') else url
            index_url = clean_base_url + "/index.html"
            chapters = crawl_chapters(page, index_url)

            if not chapters:
                logging.info(f"[SCRAPE] Failed (no chapters) for URL: {url}")
                return JSONResponse(content={"error": "Failed to crawl chapters"}, status_code=400)

            result = {
                'title': novel_details['title'],
                'author': novel_details['author'],
                'coverImg': novel_details['coverImg'],
                'chapters': chapters
            }

            logging.info(f"[SCRAPE] Completed for URL: {url}")
            return JSONResponse(content=result, status_code=200)

        except Exception as e:
            logging.error(f"[SCRAPE] Error for URL {url}: {e}")
            return JSONResponse(content={"error": str(e)}, status_code=500)
        finally:
            browser.close()


@app.get("/extract")
def extract(url: str = Query(..., description="Chapter URL"), headless: bool = True):
    logging.info(f"[EXTRACT] Started extraction for: {url}")
    try:
        content = extract_single_chapter(url, headless=headless)
        if content:
            logging.info(f"[EXTRACT] Completed successfully for: {url}")
            return JSONResponse(content={"success": True, "content": content})
        else:
            logging.info(f"[EXTRACT] Failed (no content) for: {url}")
            return JSONResponse(content={"success": False, "error": "Failed to extract content"}, status_code=400)
    except Exception as e:
        logging.error(f"[EXTRACT] Error for URL {url}: {e}")
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)


@app.post("/translate")
def translate_endpoint(payload: TranslateRequest = Body(...)) -> Dict[str, Any]:
    logging.info(f"[TRANSLATE] Started translation for Novel ID: {payload.novel_id}, Chapter: {payload.chapter_name}")

    text = payload.text.strip()
    chapter_name = payload.chapter_name.strip()
    novel_id = payload.novel_id.strip()
    
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    if not chapter_name:
        raise HTTPException(status_code=400, detail="Chapter name cannot be empty")
    if not novel_id:
        raise HTTPException(status_code=400, detail="Novel ID cannot be empty")

    glossary = get_novel_glossary(novel_id)
    chapter_title, translation, new_terms = translate_text_openrouter(text, chapter_name, glossary)

    added = 0
    if new_terms:
        success = update_novel_glossary(novel_id, new_terms)
        if success:
            added = len(new_terms)
            glossary = get_novel_glossary(novel_id)

    logging.info(f"[TRANSLATE] Completed translation for Novel ID: {novel_id}, Chapter: {chapter_name} (Added {added} new terms)")

    return {
        "chapter_title": chapter_title,
        "translation": translation,
        "new_terms": new_terms,
        "glossary": glossary,
        "terms_added": added
    }
