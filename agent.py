"""
agent.py — the FitFindr planning loop.
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

_SIZE_TOKENS = {"XS", "S", "M", "L", "XL", "XXL"}
_FILLER_PATTERNS = [
    r"\blooking for\b", r"\bunder\b", r"\bin\b", r"\bsize\b",
    r"\bi'm\b", r"\bi am\b", r"\bi\b",
]


def parse_query(query: str) -> tuple[str, str | None, float | None]:
    """
    Extract (description, size, max_price) from a free-text query.
    Only the FIRST sentence is used for description/size/price extraction —
    later sentences (e.g. "I mostly wear baggy jeans...") describe the user's
    existing wardrobe, not what they're searching for, and must not pollute
    the search keywords.
    """
    first_sentence = re.split(r"(?<=[.?!])\s+", query.strip())[0]
    working = first_sentence

    # max_price: first "$NN" or "$NN.NN" in the first sentence
    price_match = re.search(r"\$(\d+(?:\.\d+)?)", working)
    max_price = float(price_match.group(1)) if price_match else None
    if price_match:
        working = working[: price_match.start()] + working[price_match.end():]

    # size: prefer an explicit "size X" phrase
    size = None
    size_match = re.search(r"size\s+([A-Za-z0-9./]+)", working, re.IGNORECASE)
    if size_match:
        size = size_match.group(1)
        working = working[: size_match.start()] + working[size_match.end():]
    else:
        # fall back to a standalone size token (case-sensitive, so lowercase
        # words inside other words/sentences don't accidentally match)
        token_match = re.search(r"(?<![A-Za-z])(XXL|XL|XS|S|M|L)(?![A-Za-z])", working)
        if token_match:
            size = token_match.group(1)
            working = working[: token_match.start()] + working[token_match.end():]

    for pattern in _FILLER_PATTERNS:
        working = re.sub(pattern, " ", working, flags=re.IGNORECASE)
    working = re.sub(r"[,.!?$]", " ", working)
    description = re.sub(r"\s+", " ", working).strip()

    return description, size, max_price


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    return {
        "query": query,
        "parsed": {},
        "search_results": [],
        "selected_item": None,
        "wardrobe": wardrobe,
        "outfit_suggestion": None,
        "fit_card": None,
        "error": None,
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. See planning.md for the full design rationale.
    """
    session = _new_session(query, wardrobe)

    # Step 1: parse the query
    description, size, max_price = parse_query(query)
    session["parsed"] = {"description": description, "size": size, "max_price": max_price}

    # Step 2: search — this is the only branch point that changes which
    # tools get called downstream
    results = search_listings(description, size=size, max_price=max_price)
    session["search_results"] = results

    if not results:
        filters = f"'{description}'"
        if size:
            filters += f" in size {size}"
        if max_price:
            filters += f" under ${max_price}"
        session["error"] = (
            f"No listings matched {filters}. Try removing the size filter or "
            f"raising your budget."
        )
        return session  # do NOT call suggest_outfit or create_fit_card

    # Step 3: pick the top result, hand it forward
    session["selected_item"] = results[0]

    # Step 4: outfit suggestion — always runs once we have a selected item;
    # suggest_outfit handles the empty-wardrobe case internally
    session["outfit_suggestion"] = suggest_outfit(session["selected_item"], wardrobe)

    # Step 5: fit card — built from the outfit suggestion + selected item
    session["fit_card"] = create_fit_card(session["outfit_suggestion"], session["selected_item"])

    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers.",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Parsed: {session['parsed']}")
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")