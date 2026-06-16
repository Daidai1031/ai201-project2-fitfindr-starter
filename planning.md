# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

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
---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

The `session` dict (already scaffolded in `agent.py`) is the single object passed through the whole interaction. Each step writes to it and the next step reads from it — no tool ever receives raw user input directly except `search_listings`, which gets the parsed pieces.
 
Query parsing rules (regex-based, not LLM-based — cheap, deterministic, and the input format is narrow):
- `max_price`: search for `\$(\d+(?:\.\d+)?)` anywhere in the query; if found, that number becomes `max_price`. If absent, `None`.
- `size`: search for the pattern `size\s+([A-Za-z/]+)` (case-insensitive) first; if not found, fall back to scanning for standalone tokens matching `{XS, S, M, L, XL, XXL}` as whole words. If neither matches, `None`. This matters because a query like "I mostly wear baggy jeans" should *not* get misread as a size filter just because it contains clothing words.
- `description`: the query with the matched price/size substrings and filler words ("looking for", "under", "in", "size") stripped out; whatever's left is passed as keywords.
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

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->
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

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

**Milestone 4 — Planning loop and state management:**

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? -->
 **Parse:** Regex finds `$30` → `max_price = 30.0`. No "size X" pattern and no standalone size token (note: "baggy jeans" does *not* match the size-token regex, which is the point of using a narrow pattern). `size = None`. Remaining text after stripping price/filler words → `description = "vintage graphic tee"`.


**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? -->
**Search:** `search_listings("vintage graphic tee", None, 30.0)` scores listings by keyword overlap. `lst_033` ("Vintage Band Tee — Faded Grey", $19, tags include "vintage"/"graphic tee") and `lst_006` ("Graphic Tee — 2003 Tour Bootleg Style", $24) both qualify; `lst_033` scores highest and becomes `session["selected_item"]`.


**Step 3:**
<!-- Continue until the full interaction is complete -->
**Outfit:** `suggest_outfit(selected_item, example_wardrobe)`. Wardrobe is non-empty (it has `w_001` baggy jeans and `w_007` chunky sneakers), so the LLM is prompted to pair the tee with those specific pieces: something like pairing the faded tee with the baggy dark-wash jeans and chunky white sneakers for an easy grunge look, with the black combat boots as an alternate shoe option.

**Step 4**: 

**Fit card:** `create_fit_card(outfit_suggestion, selected_item)` produces a short caption mentioning the tee, its $19 price, Depop, and the grunge/jeans pairing — phrased like a real caption, not a listing description.


**Final output to user:**
<!-- What does the user actually see at the end? -->
The Gradio UI's three panels show (1) the selected listing's title/price/platform/condition, (2) the outfit suggestion text, (3) the fit card caption — all from one query, no re-entry of the item between steps.