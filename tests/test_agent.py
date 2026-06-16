import agent
from agent import run_agent, parse_query


SAMPLE_ITEM = {
    "id": "lst_999", "title": "Test Item", "description": "a test item",
    "category": "tops", "style_tags": ["test"], "size": "M", "condition": "good",
    "price": 10.0, "colors": ["red"], "brand": None, "platform": "depop",
}


def test_no_results_sets_error_and_does_not_call_other_tools(monkeypatch):
    calls = {"suggest_outfit": False, "create_fit_card": False}
    monkeypatch.setattr(agent, "search_listings", lambda description, size, max_price: [])
    monkeypatch.setattr(agent, "suggest_outfit", lambda *a, **k: calls.__setitem__("suggest_outfit", True) or "x")
    monkeypatch.setattr(agent, "create_fit_card", lambda *a, **k: calls.__setitem__("create_fit_card", True) or "x")

    session = run_agent("designer ballgown size XXS under $5", {"items": []})

    assert session["error"] is not None
    assert session["selected_item"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None
    assert calls["suggest_outfit"] is False
    assert calls["create_fit_card"] is False


def test_happy_path_passes_state_between_tools(monkeypatch):
    received = {}

    def fake_search(description, size, max_price):
        return [SAMPLE_ITEM]

    def fake_suggest(new_item, wardrobe):
        received["suggest_outfit_item"] = new_item
        return "outfit string"

    def fake_card(outfit, new_item):
        received["create_fit_card_outfit"] = outfit
        received["create_fit_card_item"] = new_item
        return "fit card string"

    monkeypatch.setattr(agent, "search_listings", fake_search)
    monkeypatch.setattr(agent, "suggest_outfit", fake_suggest)
    monkeypatch.setattr(agent, "create_fit_card", fake_card)

    session = run_agent("test query", {"items": []})

    assert session["error"] is None
    assert session["selected_item"] == SAMPLE_ITEM
    # the exact item from search_results[0] must flow into suggest_outfit
    assert received["suggest_outfit_item"] == SAMPLE_ITEM
    # the exact outfit string from suggest_outfit must flow into create_fit_card
    assert received["create_fit_card_outfit"] == "outfit string"
    assert received["create_fit_card_item"] == SAMPLE_ITEM
    assert session["outfit_suggestion"] == "outfit string"
    assert session["fit_card"] == "fit card string"


def test_parse_query_ignores_wardrobe_sentence():
    description, size, max_price = parse_query(
        "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers."
    )
    assert "jeans" not in description
    assert "sneakers" not in description
    assert max_price == 30.0


def test_parse_query_numeric_shoe_size():
    description, size, max_price = parse_query("black combat boots size 8")
    assert size == "8"
    assert max_price is None