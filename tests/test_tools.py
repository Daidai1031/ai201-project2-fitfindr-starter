import tools
from tools import search_listings, suggest_outfit, create_fit_card


class _FakeChoice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content, raise_error=False):
        self._content = content
        self._raise_error = raise_error

    def create(self, **kwargs):
        if self._raise_error:
            raise RuntimeError("simulated network failure")
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, content, raise_error=False):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content, raise_error)})()


SAMPLE_ITEM = {
    "id": "lst_033", "title": "Vintage Band Tee — Faded Grey",
    "description": "Faded grey band-style tee.", "category": "tops",
    "style_tags": ["vintage", "grunge", "band tee"], "size": "L",
    "condition": "fair", "price": 19.0, "colors": ["grey"],
    "brand": None, "platform": "depop",
}


def test_suggest_outfit_empty_wardrobe_calls_llm_with_general_prompt(monkeypatch):
    monkeypatch.setattr(tools, "_get_groq_client", lambda: _FakeClient("Pair with neutral basics."))
    result = suggest_outfit(SAMPLE_ITEM, {"items": []})
    assert result == "Pair with neutral basics."


def test_suggest_outfit_llm_failure_returns_fallback_not_exception(monkeypatch):
    monkeypatch.setattr(tools, "_get_groq_client", lambda: _FakeClient("", raise_error=True))
    result = suggest_outfit(SAMPLE_ITEM, {"items": []})
    assert "tops" in result  # category-based fallback filled in
    assert isinstance(result, str) and len(result) > 0


def test_create_fit_card_empty_outfit_no_llm_call(monkeypatch):
    def _should_not_be_called():
        raise AssertionError("LLM should not be called for empty outfit")
    monkeypatch.setattr(tools, "_get_groq_client", _should_not_be_called)
    result = create_fit_card("", SAMPLE_ITEM)
    assert "Couldn't generate a caption" in result


def test_create_fit_card_llm_failure_returns_template_fallback(monkeypatch):
    monkeypatch.setattr(tools, "_get_groq_client", lambda: _FakeClient("", raise_error=True))
    result = create_fit_card("some outfit", SAMPLE_ITEM)
    assert "depop" in result and "19.0" in result


def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []  # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    results = search_listings("vintage tee", size="m", max_price=50)
    assert all("m" in item["size"].lower() for item in results)


def test_search_top_result_is_most_relevant():
    results = search_listings("vintage graphic tee", size=None, max_price=30)
    # the top result should contain at least 2 of the 3 query keywords
    top = results[0]
    haystack = (top["title"] + " " + top["description"] + " " + " ".join(top["style_tags"])).lower()
    keyword_hits = sum(1 for kw in ("vintage", "graphic", "tee") if kw in haystack)
    assert keyword_hits >= 2