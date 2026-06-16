# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools
 
### Tool 1: search_listings
 
**What it does:**
Searches the 40-item mock listings dataset for items whose title/description/style_tags overlap with the user's description keywords, optionally filtered by size and a max price ceiling. Returns matches ranked by keyword relevance.
 
**Input parameters:**
- `description` (str): free-text keywords describing what the user wants (e.g. "vintage graphic tee"). Tokenized and lowercased for matching against each listing's `title`, `description`, and `style_tags`.
- `size` (str | None): a size string to filter by (e.g. "M"). Matching is case-insensitive substring matching against the listing's `size` field, so "M" matches "S/M" or "M/L". `None` skips size filtering entirely.
- `max_price` (float | None): inclusive price ceiling. `None` skips price filtering entirely.
**What it returns:**
A list of listing dicts (the same shape as `listings.json`: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted highest-relevance first. Relevance = count of description keywords found in the listing's title/description/style_tags. Listings with a relevance score of 0 are dropped even if they pass the price/size filters — a $20 belt that happens to be under budget is not a match for "graphic tee."
 
**What happens if it fails or returns nothing:**
Returns `[]` — never raises. The agent (planning loop) is responsible for noticing the empty list, telling the user nothing matched and naming the filters that were applied (description / size / price), suggesting they loosen one of them, and stopping before calling `suggest_outfit`.
 
---
 
### Tool 2: suggest_outfit
 
**What it does:**
Given a candidate item and the user's wardrobe, calls the LLM (Groq `llama-3.3-70b-versatile`) to propose 1–2 complete outfit pairings. If the wardrobe has items, it names specific wardrobe pieces by their `name` field. If the wardrobe is empty, it falls back to general styling advice about the new item alone (what it pairs well with in the abstract).
 
**Input parameters:**
- `new_item` (dict): a listing dict — normally `session["selected_item"]`, the top result from `search_listings`.
- `wardrobe` (dict): `{"items": [...]}`. May have `items == []` for a new user.
**What it returns:**
A non-empty string: either a wardrobe-specific outfit suggestion (referencing item names like "your chunky white sneakers") or, if the wardrobe is empty, general styling guidance for the new item alone. Either way the string is never blank.
 
**What happens if it fails or returns nothing:**
Empty wardrobe is not treated as an error — it's a known, expected branch with its own prompt. If the Groq API call itself throws (network error, bad key, rate limit), the function catches the exception and returns a hardcoded fallback string built from the item's `category` and `style_tags` (e.g. "Try pairing this [category] with a neutral base piece — couldn't reach the styling assistant right now."), so the session never crashes on a network blip.
 
---
 
### Tool 3: create_fit_card
 
**What it does:**
Turns the outfit suggestion and item details into a short, casual caption — the kind of thing someone would actually post, not a product blurb. Calls the LLM at a higher temperature (≥0.9) so repeated calls on the same input vary.
 
**Input parameters:**
- `outfit` (str): the string returned by `suggest_outfit`.
- `new_item` (dict): the listing dict the caption is about.
**What it returns:**
A 2–4 sentence string mentioning the item, its price, and its platform once each, naturally, plus the outfit vibe in specific terms (not "great outfit!" — actual texture/color/style words).
 
**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the function returns a descriptive error string (e.g. "Can't generate a caption — no outfit details were provided.") **without calling the LLM at all**. If the LLM call itself fails, it's caught and a template-based fallback caption is returned instead (built directly from `new_item`'s title/price/platform, no styling language) — informative degradation rather than a crash.
 
---
 
## Planning Loop
 
The loop is a fixed sequence of *conditional* steps, not a fixed sequence of *calls*. After each tool call, it inspects what came back before deciding whether to proceed:
 
1. Parse the raw query string into `description`, `size`, `max_price` using regex (see State Management below for the exact rules). Store in `session["parsed"]`.
2. Call `search_listings(**parsed)`. If `len(results) == 0`: set `session["error"]` to a specific message naming the filters used, and **return the session immediately** — `suggest_outfit` and `create_fit_card` are never called on this path.
3. If results exist: set `session["selected_item"] = results[0]` and continue.
4. Call `suggest_outfit(selected_item, wardrobe)`. This call always happens if step 2 produced a result — there's no branch here because the tool itself handles the empty-wardrobe case internally. Store the result in `session["outfit_suggestion"]`.
5. Call `create_fit_card(outfit_suggestion, selected_item)`. Store in `session["fit_card"]`.
6. Return the session.
The only branch point that changes which tools get called is step 2 (empty vs. non-empty search results). Everything downstream of a successful search always runs — the agent doesn't second-guess a non-empty `outfit_suggestion`, because `suggest_outfit` is contractually required to never return an empty string.
 
---
 
## State Management
 
The `session` dict (already scaffolded in `agent.py`) is the single object passed through the whole interaction. Each step writes to it and the next step reads from it — no tool ever receives raw user input directly except `search_listings`, which gets the parsed pieces.
 
Query parsing rules (regex-based, not LLM-based — cheap, deterministic, and the input format is narrow). **Only the first sentence of the query is parsed** for description/size/price — later sentences (e.g. "I mostly wear baggy jeans...") describe the wardrobe context, not the search target, and including them would pollute the keyword match:
- `max_price`: search for `\$(\d+(?:\.\d+)?)` in the first sentence; if found, that number becomes `max_price`. If absent, `None`.
- `size`: search for the pattern `size\s+([A-Za-z0-9./]+)` (case-insensitive) first — note this must allow digits, not just letters, or numeric shoe sizes like "size 8" silently fail to extract (caught during testing). If not found, fall back to scanning for standalone tokens matching `{XS, S, M, L, XL, XXL}` as whole words. If neither matches, `None`.
- `description`: the first sentence with the matched price/size substrings and filler words ("looking for", "under", "in", "size", "i'm", "i am", "i") stripped out; whatever's left is passed as keywords.
- Implementation note: the keyword tokenizer must treat contractions as single tokens (e.g. `"i'm"`) rather than splitting on the apostrophe — otherwise `"I'm"` becomes stray tokens `"i"` and `"m"`, and the `"m"` token can spuriously affect matching since it never gets caught by the stopword list. Found this during Milestone 5-style testing of the parser, not from the original spec.
State flow: `session["selected_item"]` (written after `search_listings`) is the exact dict passed by reference into `suggest_outfit`, and `session["outfit_suggestion"]` (written after `suggest_outfit`) is passed by reference into `create_fit_card` along with the same `selected_item`. Nothing is re-derived or re-entered by the user between steps.
 
---
 
## Error Handling
 
| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | `session["error"] = "No listings matched '{description}'" + (f" in size {size}" if size) + (f" under ${max_price}" if max_price) + ". Try removing the size filter or raising your budget."` Loop returns immediately; `suggest_outfit`/`create_fit_card` are not called. |
| suggest_outfit | Wardrobe is empty | Not an error — tool switches to a "general styling advice" prompt internally and still returns a non-empty string. Session proceeds normally. |
| suggest_outfit | Groq API call throws | Caught inside the tool; returns a hardcoded fallback string derived from the item's category/style_tags so the session still completes. |
| create_fit_card | `outfit` is empty/whitespace | Returns `"Couldn't generate a caption — outfit details were incomplete."` without calling the LLM. Session still returns with `fit_card` set to this message rather than `None`, so the UI always has something to show. |
| create_fit_card | Groq API call throws | Caught inside the tool; returns a template caption built directly from `new_item` fields (title, price, platform) with no styling language. |
 
---
 
## Architecture
 
```
User query + wardrobe
        │
        ▼
   Planning Loop (run_agent)
        │
        ├─► Step 1: parse_query(query) → description, size, max_price
        │         Session: parsed = {...}
        │
        ├─► Step 2: search_listings(description, size, max_price)
        │       │
        │       ├─ results = []
        │       │      └─► [ERROR] session["error"] = "No listings found..." → RETURN early
        │       │
        │       └─ results = [item, ...]
        │              Session: search_results = results
        │              Session: selected_item = results[0]
        │
        ├─► Step 3: suggest_outfit(selected_item, wardrobe)
        │       │
        │       ├─ wardrobe["items"] empty   → LLM general-styling prompt
        │       └─ wardrobe["items"] present → LLM outfit-pairing prompt (names pieces)
        │              Session: outfit_suggestion = "..."
        │
        ├─► Step 4: create_fit_card(outfit_suggestion, selected_item)
        │       │
        │       ├─ outfit_suggestion blank → error string, no LLM call
        │       └─ otherwise                → LLM caption prompt (temperature ≥ 0.9)
        │              Session: fit_card = "..."
        │
        ▼
   Return session ◄─────────────────────────────────── error path also returns session here
```
 
---
 
## AI Tool Plan
 
**Milestone 3 — Individual tool implementations:**
I'll use Claude, one tool at a time. For `search_listings`, I'll paste the Tool 1 block above (params, return shape, failure mode) plus the docstring of `load_listings()`, and ask Claude to implement the keyword-scoring search. Before running it, I'll check: does it filter by `max_price`/`size` *before* scoring, does it drop zero-score listings, does it sort descending, and does it return `[]` (not raise) on no match? Then I'll run the three pytest cases from the assignment plus one manual no-match query.
 
For `suggest_outfit` and `create_fit_card`, I'll give Claude their respective spec blocks plus a note that both must use the existing `_get_groq_client()` helper and `llama-3.3-70b-versatile`. Before running, I'll check that the empty-wardrobe / empty-outfit guards happen *before* any LLM call (not after a failed call), and that `create_fit_card` sets temperature ≥ 0.9 — I'll verify this by running it 3 times on identical input and confirming the captions differ.
 
**Milestone 4 — Planning loop and state management:**
I'll share the Architecture diagram and the Planning Loop + State Management sections above with Claude and ask it to implement `run_agent()` and `_new_session()`. Before trusting the output, I'll check three things: (a) it does not call `suggest_outfit` when `search_results` is empty, (b) every intermediate value (`selected_item`, `outfit_suggestion`, `fit_card`) is written into the `session` dict rather than kept as a local variable, and (c) the no-results path returns early with `session["error"]` set and `fit_card` left as `None`. I'll verify state-passing concretely by printing `id(session["selected_item"])` before and after the `suggest_outfit` call to confirm it's the same object, not a re-derived copy.
 
---
 
## A Complete Interaction (Step by Step)
 
**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"
 
**Step 1 — Parse:** Regex finds `$30` → `max_price = 30.0`. No "size X" pattern and no standalone size token (note: "baggy jeans" does *not* match the size-token regex, which is the point of using a narrow pattern). `size = None`. Remaining text after stripping price/filler words → `description = "vintage graphic tee"`.
 
**Step 2 — Search:** `search_listings("vintage graphic tee", None, 30.0)` scores listings by keyword overlap. Both `lst_002` ("Y2K Baby Tee — Butterfly Print", $18, tags include "vintage"/"graphic tee") and `lst_033` / `lst_006` score 3 (all three keywords match). `lst_002` wins the tie because it appears earliest in `listings.json` — relevance scoring alone doesn't break ties by "most iconic match," just by score then list order. It becomes `session["selected_item"]`. *(Divergence from the original plan: I'd assumed the band tee would win; testing showed the actual tie-break behavior, which is worth calling out in the README's spec reflection rather than silently leaving the walkthrough wrong.)*
 
**Step 3 — Outfit:** `suggest_outfit(selected_item, example_wardrobe)`. Wardrobe is non-empty (it has `w_001` baggy jeans and `w_007` chunky sneakers), so the LLM is prompted to pair the tee with those specific pieces: something like pairing the faded tee with the baggy dark-wash jeans and chunky white sneakers for an easy grunge look, with the black combat boots as an alternate shoe option.
 
**Step 4 — Fit card:** `create_fit_card(outfit_suggestion, selected_item)` produces a short caption mentioning the tee, its $19 price, Depop, and the grunge/jeans pairing — phrased like a real caption, not a listing description.
 
**Final output to user:** The Gradio UI's three panels show (1) the selected listing's title/price/platform/condition, (2) the outfit suggestion text, (3) the fit card caption — all from one query, no re-entry of the item between steps.