import re
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, Body, HTTPException
from pydantic import BaseModel
from openai import OpenAI

# -----------------------------
# CONFIG
# -----------------------------
OPENROUTER_API_KEY = "sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxx"  # replace with your key

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
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
    Only include one term per line in the format "chinese:english"."""  # noqa

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
app = FastAPI(title="Chinese Novel Translator API", version="1.1.0")


class TranslateRequest(BaseModel):
    text: str
    glossary: Dict[str, str] = {}  # glossary provided by client


@app.post("/translate")
def translate_endpoint(payload: TranslateRequest = Body(...)) -> Dict[str, Any]:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    glossary = payload.glossary or {}
    translation, new_terms = translate_text_openrouter(text, glossary)

    return {
        "translation": translation,
        "new_terms": new_terms,
        "glossary_used": glossary,
    }


# -----------------------------
# RUN SERVER (for dev only)
# -----------------------------
if __name__ == "__main__":
    uvicorn.run("translator_api:app", host="0.0.0.0", port=8000, reload=True)
