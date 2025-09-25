# run with
# .\venv\Scripts\Activate
# uvicorn ex-nov-dtl-api:app --host 0.0.0.0 --port 8000 --reload

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
import json
import os

app = FastAPI()

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
