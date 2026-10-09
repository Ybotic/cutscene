"""Best-effort Hindi-to-Hinglish caption transliteration via OpenRouter."""

import json

from backend.settings import settings


class CaptionTranslationError(RuntimeError):
    pass


def contains_devanagari(text: str) -> bool:
    return any("\u0900" <= character <= "\u097f" for character in text)


def should_transliterate(text: str, source_language: str | None, mode: str) -> bool:
    if not text.strip() or mode == "original":
        return False
    return (source_language or "").lower().startswith("hi") or contains_devanagari(text)


def transliterate_hindi_captions(
    captions: dict[int, str], source_language: str | None, mode: str
) -> dict[int, str]:
    """Romanize detected Hindi captions while preserving English words and order."""
    output = dict(captions)
    targets = {
        caption_id: text
        for caption_id, text in captions.items()
        if should_transliterate(text, source_language, mode)
    }
    if not targets:
        return output
    if not settings.openrouter_api_key:
        raise CaptionTranslationError("OPENROUTER_API_KEY is not configured.")

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "AI Clipper",
            },
        )
        prompt_captions = [
            {"id": caption_id, "text": text}
            for caption_id, text in targets.items()
        ]
        response = client.chat.completions.create(
            model=settings.openrouter_model,
            temperature=0,
            max_tokens=4096,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Convert Hindi written in Devanagari into natural Hinglish written "
                        "in Latin letters. Transliterate Hindi; do not translate it into "
                        "English. Keep existing English words, names, numbers, punctuation, "
                        "meaning, and word order. Keep the whitespace-separated word count "
                        "the same whenever possible so caption timings remain aligned. "
                        "Return every caption exactly once in JSON "
                        "with shape {\"captions\":[{\"id\":1,\"text\":\"...\"}]}. "
                        "Do not include Devanagari in the output."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"source_language": source_language, "captions": prompt_captions},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        converted = {
            int(item["id"]): str(item["text"]).strip()
            for item in payload.get("captions", [])
            if isinstance(item, dict)
            and str(item.get("id", "")).isdigit()
            and isinstance(item.get("text"), str)
        }
        for caption_id in targets:
            if caption_id not in converted or contains_devanagari(converted[caption_id]):
                raise ValueError("The model returned an incomplete Hinglish caption.")
        output.update(converted)
        return output
    except Exception as exc:
        if isinstance(exc, CaptionTranslationError):
            raise
        raise CaptionTranslationError(f"Could not create Hinglish captions: {exc}") from exc
