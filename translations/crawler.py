import logging
import time
import re
import os
import json
from urllib.parse import urljoin
from typing import Dict, Any

from playwright.sync_api import sync_playwright
from openai import OpenAI

# -----------------------------
# CONFIG
# -----------------------------
OPENROUTER_API_KEY = "YOUR_OPENROUTER_KEY"

# -----------------------------
# LOGGING
# -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# -----------------------------
# NOVEL SCRAPER FUNCTIONS
# -----------------------------
def get_novel_details(page, base_url):
    """Extract novel details from the main book page"""
    try:
        page.wait_for_selector('div.bookbox', timeout=10000)
        bookbox = page.query_selector('div.bookbox')

        if bookbox:
            cover_img = bookbox.query_selector('div.bookimg2 img')
            cover_url = cover_img.get_attribute('src') if cover_img else None
            if cover_url and not cover_url.startswith('http'):
                cover_url = urljoin(base_url, cover_url)

            title_element = bookbox.query_selector('div.booknav2 h1 a')
            title = title_element.text_content().strip() if title_element else None

            author_element = bookbox.query_selector('div.booknav2 p:has-text("作者：") a')
            author = author_element.text_content().strip() if author_element else None
            if not author:
                author_p = bookbox.query_selector('div.booknav2 p:has-text("作者：")')
                if author_p:
                    author_text = author_p.text_content().strip()
                    author = author_text.replace('作者：', '').strip()

            return {"title": title, "author": author, "coverImg": cover_url}
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
        return []
    except Exception as e:
        print(f"Error crawling chapters: {e}")
        return []


def extract_single_chapter(chapter_url: str, headless: bool = True):
    """Extract single chapter content"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = context.new_page()
        try:
            page.goto(chapter_url, wait_until='domcontentloaded', timeout=45000)
            time.sleep(2)
            content_element = page.query_selector('#txtcontent') or page.query_selector('.content')
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

# -----------------------------
# TRANSLATION & GLOSSARY (LOCAL ONLY)
# -----------------------------
def get_local_glossary() -> Dict[str, str]:
    """Get glossary from local file"""
    if os.path.exists("glossary.json"):
        return json.load(open("glossary.json", "r", encoding="utf-8"))
    return {}


def update_local_glossary(new_terms: Dict[str, str]) -> None:
    """Update glossary locally"""
    glossary = get_local_glossary()
    glossary.update(new_terms)
    with open("glossary.json", "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)


def translate_text_openrouter(text: str, chapter_name: str, glossary: Dict[str, str]):
    """Translate Chinese text and chapter name"""
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

    glossary_context = ""
    if glossary:
        glossary_context = "Use the following glossary for proper nouns:\n"
        for chinese, english in glossary.items():
            glossary_context += f"{chinese} -> {english}\n"

    system_prompt = """You are a professional translator from Chinese to English.
Translate the title and chapter text naturally. Use glossary when available.
Output strictly:
CHAPTER_TITLE: ...
TRANSLATION: ...
NEW_TERMS: ..."""

    user_prompt = f"""{glossary_context}
Chapter Title: {chapter_name}
Chapter Content:
{text}"""

    response = client.chat.completions.create(
        model="x-ai/grok-4-fast:free",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    response_text = response.choices[0].message.content

    chapter_title_match = re.search(r"CHAPTER_TITLE:\s*(.*?)(?=TRANSLATION:|$)", response_text, re.DOTALL)
    translation_match = re.search(r"TRANSLATION:\s*(.*?)(?=NEW_TERMS:|$)", response_text, re.DOTALL)
    new_terms_match = re.search(r"NEW_TERMS:\s*([\s\S]*)", response_text)

    chapter_title = chapter_title_match.group(1).strip() if chapter_title_match else chapter_name
    translation = translation_match.group(1).strip() if translation_match else response_text

    new_terms = {}
    if new_terms_match:
        for line in new_terms_match.group(1).splitlines():
            if ":" in line:
                chinese, english = map(str.strip, line.split(":", 1))
                if chinese and english:
                    new_terms[chinese] = english
    return chapter_title, translation, new_terms

# -----------------------------
# CLI MAIN PROGRAM
# -----------------------------
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        novel_url = input("Enter novel URL: ").strip()
        page.goto(novel_url, wait_until='domcontentloaded')
        novel_details = get_novel_details(page, novel_url)

        clean_base_url = novel_url[:-5] if novel_url.endswith('.html') else novel_url
        index_url = clean_base_url + "/index.html"
        chapters = crawl_chapters(page, index_url)
        browser.close()

    print(f"\nNovel: {novel_details['title']} by {novel_details['author']}")
    for i, ch in enumerate(chapters[:20]):  # show first 20 chapters
        print(f"{i+1}. {ch['chapter_name']}")

    choice = int(input("\nSelect chapter number to start from: ")) - 1
    mode = input("Translate only this chapter (1) or all following chapters (2)? ")

    glossary = get_local_glossary()

    start = choice
    end = len(chapters) if mode == "2" else choice + 1

    for i in range(start, end):
        chapter = chapters[i]
        print(f"\n[PROCESSING] {chapter['chapter_name']}")

        chinese_text = extract_single_chapter(chapter['url'])
        if not chinese_text:
            print("Failed to extract chapter content, skipping.")
            continue

        chapter_title, translation, new_terms = translate_text_openrouter(chinese_text, chapter['chapter_name'], glossary)
        if new_terms:
            update_local_glossary(new_terms)
            glossary.update(new_terms)

        safe_title = re.sub(r'[\\/*?:"<>|]', "_", chapter_title)
        filename = f"{safe_title}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"{chapter_title}\n\n{translation}")

        print(f"[SAVED] {filename}")


if __name__ == "__main__":
    main()
