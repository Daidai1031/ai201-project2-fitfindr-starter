"""
tools.py — FitFindr tools.
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

_STOPWORDS = {
    "a", "an", "the", "for", "in", "of", "with", "and", "or", "size",
    "under", "less", "than", "looking", "i'm", "im", "want", "need",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase, keep contractions intact, split on whitespace/punctuation, drop stopwords."""
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.
    """
    listings = load_listings()

    # Step 1: hard filters — price and size — applied before any scoring.
    candidates = []
    for item in listings:
        if max_price is not None and item["price"] > max_price:
            continue
        if size is not None and size.lower() not in item["size"].lower():
            continue
        candidates.append(item)

    # Step 2: score remaining candidates by keyword overlap against
    # title + description + style_tags.
    keywords = _tokenize(description)
    scored = []
    for item in candidates:
        haystack = _tokenize(
            item["title"] + " " + item["description"] + " " + " ".join(item["style_tags"])
        )
        score = len(keywords & haystack)
        if score > 0:
            scored.append((score, item))

    # Step 3: sort highest-score first, return just the listing dicts.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

_GENERAL_STYLING_FALLBACK = (
    "Couldn't reach the styling assistant right now — as a general rule, this "
    "{category} pairs well with neutral, simple pieces so the item itself can stand out."
)

_WARDROBE_STYLING_FALLBACK = (
    "Couldn't reach the styling assistant right now — try pairing this {category} "
    "with whatever neutral basics you already wear most."
)


def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1-2 complete outfits.
    Empty wardrobe -> general styling advice. Non-empty -> names specific pieces.
    LLM call failure -> caught, hardcoded fallback returned (never raises).
    """
    items = wardrobe.get("items", [])

    if not items:
        prompt = (
            f"Someone is considering buying this secondhand item:\n"
            f"Title: {new_item['title']}\n"
            f"Category: {new_item['category']}\n"
            f"Style tags: {', '.join(new_item['style_tags'])}\n"
            f"Colors: {', '.join(new_item['colors'])}\n\n"
            f"They don't have a wardrobe on file yet. Give general styling advice "
            f"for this item in 2-3 sentences: what kinds of pieces it pairs well "
            f"with, what vibe/aesthetic it suits. Be specific and concrete, not generic."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it['category']}, {', '.join(it['colors'])})"
            + (f" — {it['notes']}" if it.get("notes") else "")
            for it in items
        )
        prompt = (
            f"Someone is considering buying this secondhand item:\n"
            f"Title: {new_item['title']}\n"
            f"Category: {new_item['category']}\n"
            f"Style tags: {', '.join(new_item['style_tags'])}\n"
            f"Colors: {', '.join(new_item['colors'])}\n\n"
            f"Here is their current wardrobe:\n{wardrobe_lines}\n\n"
            f"Suggest 1-2 complete outfits that pair this new item with SPECIFIC "
            f"named pieces from their wardrobe above. Reference items by name. "
            f"Keep it to 2-4 sentences, concrete and wearable, not generic."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        result = response.choices[0].message.content.strip()
        return result if result else _GENERAL_STYLING_FALLBACK.format(category=new_item["category"])
    except Exception:
        template = _GENERAL_STYLING_FALLBACK if not items else _WARDROBE_STYLING_FALLBACK
        return template.format(category=new_item["category"])


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.
    Empty/whitespace outfit -> descriptive error string, no LLM call.
    LLM call failure -> caught, template-based fallback caption (never raises).
    """
    if not outfit or not outfit.strip():
        return "Couldn't generate a caption — no outfit details were provided."

    prompt = (
        f"Write a short, casual Instagram/TikTok caption (2-4 sentences) for an "
        f"OOTD post featuring a secondhand find. It should sound like a real person "
        f"posting, not a product listing — casual tone, maybe a little slang or an "
        f"emoji, not salesy.\n\n"
        f"Item: {new_item['title']}\n"
        f"Price: ${new_item['price']}\n"
        f"Platform: {new_item['platform']}\n"
        f"Outfit styling: {outfit}\n\n"
        f"Mention the item, price, and platform naturally and only once each. "
        f"Capture the specific vibe of the outfit, not generic enthusiasm."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.95,
        )
        result = response.choices[0].message.content.strip()
        if result:
            return result
    except Exception:
        pass

    # Template fallback if the LLM call failed or returned nothing
    return (
        f"thrifted this {new_item['title'].lower()} on {new_item['platform']} for "
        f"${new_item['price']} 🖤"
    )