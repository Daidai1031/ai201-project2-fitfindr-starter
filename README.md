# FitFindr

An agent that finds secondhand clothing listings, suggests outfits using the user's wardrobe, and generates a shareable caption — built around three tools orchestrated by a planning loop.

## Setup

```
pip install -r requirements.txt
echo "GROQ_API_KEY=your_key_here" > .env
python app.py
```

## Tools

### `search_listings(description: str, size: str | None = None, max_price: float | None = None) -> list[dict]`

Searches the 40-item mock listings dataset for items whose title, description, or style tags overlap with `description`'s keywords, optionally filtered by `size` (case-insensitive substring match against the listing's size field) and `max_price` (inclusive ceiling). Hard filters (price, size) are applied first; remaining listings are scored by keyword overlap and sorted highest-first. Listings that pass the filters but score zero on keyword overlap are dropped. Returns `[]` (never raises) when nothing matches.

### `suggest_outfit(new_item: dict, wardrobe: dict) -> str`

Given a candidate listing and a wardrobe (`{"items": [...]}`), calls Groq's `llama-3.3-70b-versatile` to propose 1-2 outfit pairings. If `wardrobe["items"]` is non-empty, the prompt instructs the model to name specific wardrobe pieces. If empty, it switches to a general-styling prompt with no wardrobe references. Always returns a non-empty string — a Groq API failure is caught and replaced with a hardcoded fallback derived from the item's category.

### `create_fit_card(outfit: str, new_item: dict) -> str`

Turns an outfit suggestion and item details into a short, casual caption (temperature 0.95 so repeated calls vary). If `outfit` is empty or whitespace, returns an error string immediately **without calling the LLM**. If the LLM call itself fails, falls back to a template caption built from the item's title/price/platform.

## Planning Loop

`run_agent()` in `agent.py` runs a fixed sequence of steps, but only one of them branches based on what comes back:

1. `parse_query()` extracts `description`, `size`, and `max_price` from the raw query using regex — only the first sentence is parsed, so a query like *"...under $30. I mostly wear baggy jeans..."* doesn't have the wardrobe-context sentence bleeding into the search keywords.
2. `search_listings()` runs with the parsed parameters. **This is the only branch point that changes which tools get called.** If it returns `[]`, `session["error"]` is set to a message naming the filters that were applied, and the function returns immediately — `suggest_outfit` and `create_fit_card` are never reached.
3. If results exist, `results[0]` becomes `session["selected_item"]`, and `suggest_outfit()` is called unconditionally — it doesn't need a branch here because the tool itself handles the empty-wardrobe case internally.
4. `create_fit_card()` is called with the outfit suggestion and selected item, and the session is returned.

## State Management

A single `session` dict is threaded through the whole interaction (`query`, `parsed`, `search_results`, `selected_item`, `wardrobe`, `outfit_suggestion`, `fit_card`, `error`). Each tool call writes its result into this dict before the next tool reads from it — `selected_item` is the exact object returned by `search_listings`, passed by reference into `suggest_outfit`, and `outfit_suggestion` is passed the same way into `create_fit_card`. Nothing is re-derived or re-entered by the user mid-session; this was verified directly by checking `id(session["selected_item"])` before and after the `suggest_outfit` call.

## Error Handling

| Tool | Failure mode | Agent response | Verified example |
|------|-------------|----------------|-------------------|
| `search_listings` | No results match | Returns `[]`; loop sets `session["error"]` naming the filters used and returns before calling the other tools | `"No listings matched 'designer ballgown' in size XXS under $5.0. Try removing the size filter or raising your budget."` |
| `suggest_outfit` | Empty wardrobe | Switches to a general-styling prompt internally; not treated as an agent-level error | Same item, empty wardrobe, produced generic advice (mom jeans, flowy skirts, cardigans) with zero named pieces — visibly different from the wardrobe-aware version, which named four specific closet items by name |
| `create_fit_card` | Empty outfit string | Returns a fixed error string with **no LLM call** | `create_fit_card('', item)` returned `"Couldn't generate a caption — no outfit details were provided."` instantly, confirming the guard runs before any network call |

## Spec Reflection

Writing out each tool's exact failure-mode response in `planning.md` *before* coding caught a design decision I would have otherwise made ad hoc: deciding that an empty wardrobe is a normal, expected branch (general styling advice) rather than an agent-level error, while an empty outfit string in `create_fit_card` *is* treated as an error. Without writing that distinction down first, it would have been easy to handle both the same way.

Where implementation diverged from the spec: the original `planning.md` walkthrough assumed the "Vintage Band Tee" would be `search_listings`'s top result for "vintage graphic tee," but testing showed a tie (multiple listings score equally on keyword overlap) gets broken by list order in `listings.json`, not by which match feels most "iconic." The walkthrough was corrected to match the actual tested behavior rather than left wrong. Two parsing bugs also only surfaced from running real example queries, not from anything ambiguous in the spec's wording: the size-extraction regex only matched letters, so `"size 8"` (a shoe size) silently failed to extract; and the keyword tokenizer split `"I'm"` on its apostrophe into stray `"i"`/`"m"` tokens, bypassing the intended stopword filter.

## AI Usage

**Instance 1 — implementing the three tools.** I gave Claude the Tool 1/2/3 spec blocks from `planning.md` (exact parameters, return shape, failure mode) one at a time and asked it to implement each function in `tools.py`. Before trusting the output, I ran it against real data: `search_listings` against the three required pytest cases plus a manual relevance check, and `suggest_outfit`/`create_fit_card` against mocked Groq clients (since I didn't want real API calls inside unit tests) to confirm the empty-wardrobe and empty-outfit guards actually short-circuit before any LLM call. That testing surfaced the two regex bugs above, which I had Claude fix directly rather than working around in the tests.

**Instance 2 — implementing the planning loop.** I shared the Architecture diagram and the Planning Loop/State Management sections of `planning.md` and asked Claude to implement `run_agent()`. I verified the generated code didn't call `suggest_outfit` on an empty search result by mocking all three tools and asserting (via pytest) that the mocked `suggest_outfit`/`create_fit_card` were never invoked on the no-results path, and separately asserted that the exact object returned by `search_listings` flows unchanged into `suggest_outfit` and `create_fit_card`.

**Instance 3 — debugging a pytest import error.** Running `pytest` directly on Windows produced `ModuleNotFoundError: No module named 'tools'` even though the same tests passed via `python -m pytest`. Claude diagnosed this as pytest's import-mode behavior (no `__init__.py` in `tests/` means pytest doesn't add the project root to `sys.path`), reproduced the exact failure in a sandbox first, then confirmed a fix (an empty root-level `conftest.py`) actually resolved it before I applied it — rather than just asserting it would work.