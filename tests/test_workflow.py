from shop_buddy.settings import Settings
from shop_buddy.store import ShopStore
from shop_buddy.workflow import ShopWorkflow


def make_workflow(tmp_path):
    settings = Settings(
        database_path=tmp_path / "shop-buddy-test.db",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        gemini_api_key=None,
        gemini_model="gemini-3.5-flash",
        workflow_mode="langgraph",
    )
    return ShopWorkflow(ShopStore(settings.database_path), settings)


def test_search_add_update_and_delete_follow_up(tmp_path):
    workflow = make_workflow(tmp_path)
    first = workflow.run("Show me office chairs under $500", "shopper-a")
    assert first["intent"] == "search"
    assert len(first["products"]) == 3
    assert first["tool_results"][0]["tool"] == "Search Products"

    added = workflow.run("Add the second one to my cart", "shopper-a")
    assert added["cart"]["item_count"] == 1
    assert added["cart"]["items"][0]["title"] == "Cedar Executive Chair"
    assert added["tool_results"][0]["tool"] == "AddProductToCart"

    updated = workflow.run("Change quantity to 3", "shopper-a")
    assert updated["cart"]["items"][0]["quantity"] == 3

    removed = workflow.run("Remove it from my cart", "shopper-a")
    assert removed["cart"]["items"] == []


def test_combined_search_and_cart_request(tmp_path):
    workflow = make_workflow(tmp_path)
    result = workflow.run("Find an office chair under $500 and add it to my cart", "shopper-b")
    assert result["intent"] == "combined"
    assert result["products"]
    assert result["cart"]["item_count"] == 1


def test_memory_survives_a_new_langgraph_workflow_instance(tmp_path):
    first_workflow = make_workflow(tmp_path)
    first_workflow.run("Show me office chairs under $500", "persistent-shopper")

    # This models a browser refresh or backend restart: the in-process graph is
    # new, while SQLite conversation state must still resolve "the second one".
    resumed_workflow = make_workflow(tmp_path)
    result = resumed_workflow.run("Add the second one to my cart", "persistent-shopper")

    assert result["cart"]["items"][0]["title"] == "Cedar Executive Chair"


def test_possessive_pronoun_updates_previously_selected_product(tmp_path):
    workflow = make_workflow(tmp_path)
    session = "possessive-follow-up"
    workflow.run("Show me office chairs under $500.", session)
    workflow.run("Add the second one to my cart.", session)

    result = workflow.run("Increase its quantity to 3.", session)

    assert result["cart"]["items"][0]["title"] == "Cedar Executive Chair"
    assert result["cart"]["items"][0]["quantity"] == 3


def test_reference_acceptance_queries_work_without_an_api_key(tmp_path):
    workflow = make_workflow(tmp_path)
    session = "brief-acceptance"

    affordable = workflow.run("Show me affordable chairs.", session)
    assert affordable["products"]
    assert all("chair" in product["title"].lower() or "seating" in product["category"].lower() for product in affordable["products"])

    desks = workflow.run("Find a desk under 5000.", session)
    assert desks["products"]
    assert all(product["price"] <= 5000 for product in desks["products"])

    added = workflow.run("Add 2 conference chairs to my cart.", session)
    assert added["cart"]["item_count"] == 2
    assert added["cart"]["items"][0]["title"] == "Forum Conference Chair"

    updated = workflow.run("Change quantity to 3.", session)
    assert updated["cart"]["items"][0]["quantity"] == 3

    viewed = workflow.run("Show my cart.", session)
    assert viewed["cart"]["item_count"] == 3

    deleted = workflow.run("Remove the conference chairs from my cart.", session)
    assert deleted["cart"]["items"] == []


def test_crewai_result_reconciles_agent_mutations_and_applies_request_once(tmp_path):
    settings = Settings(
        database_path=tmp_path / "crewai-reconcile.db",
        openai_api_key="configured-for-test",
        openai_base_url="https://example.invalid/v1",
        openai_model="gpt-4o-mini",
        gemini_api_key=None,
        gemini_model="gemini-3.5-flash",
        workflow_mode="crewai",
    )
    # Construct only the shared supervisor. This test does not need to build or
    # call the external CrewAI provider.
    workflow = ShopWorkflow.__new__(ShopWorkflow)
    workflow.store = ShopStore(settings.database_path)
    workflow.settings = settings
    session = "crewai-reconcile"
    before = workflow.store.get_cart(session)

    # Model an agent retry that added the wrong product before returning.
    workflow.store.add_to_cart(session, product_id=2, quantity=4)
    added = workflow._framework_result(
        "Add 2 office chairs to my cart.", session, "Crew completed.", before
    )

    assert [(item["title"], item["quantity"]) for item in added["cart"]["items"]] == [
        ("AeroMesh Office Chair", 2)
    ]
    assert any(item["tool"] == "AddProductToCart" for item in added["tool_results"])
    assert added["trace"][0] == {
        "agent": "CrewAI Multi-Agent Runtime",
        "status": "completed",
        "detail": "Specialized agents collaborated and returned a workflow result.",
    }

    updated = workflow._framework_result(
        "Update office chairs quantity to 3.",
        session,
        "Crew completed.",
        workflow.store.get_cart(session),
    )
    assert updated["cart"]["items"][0]["quantity"] == 3
