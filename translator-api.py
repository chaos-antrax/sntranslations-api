# run with
# .\venv\Scripts\Activate
# uvicorn translator-api:app --host 0.0.0.0 --port 8000 --reload

import os
import re
import json
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, Body, HTTPException
from pydantic import BaseModel
from openai import OpenAI

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
    TRANSLATION: [your translation text here]
    NEW TERMS: [chinese:english, chinese:english, chinese:english]

    Each term should be on a separate line in the NEW TERMS section.
    Only include one term per line in the format "chinese:english"."""

    user_prompt = f"{glossary_context}Translate the following text:\n\n{text}"

    response = client.chat.completions.create(
        model="deepseek/deepseek-chat-v3.1:free",
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


# -----------------------------
# FASTAPI APP
# -----------------------------
app = FastAPI(title="Chinese Novel Translator API", version="1.0.0")


class TranslateRequest(BaseModel):
    text: str


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


# -----------------------------
# RUN SERVER (for dev only)
# -----------------------------
if __name__ == "__main__":
    uvicorn.run("translator_api:app", host="0.0.0.0", port=8000, reload=True)
