"""FastAPI application and the five shopping tool endpoints."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from .models import AddProductRequest, CartOperation, ChatRequest, DeleteCartRequest, LoginRequest, PreferencesRequest, RegisterRequest, UpdateCartRequest
from .settings import get_settings
from .store import ShopStore
from .workflow import ShopWorkflow


def create_app() -> FastAPI:
    settings = get_settings()
    store = ShopStore(settings.database_path)
    workflow = ShopWorkflow(store, settings)
    app = FastAPI(title="Shop Buddy API", version="1.0.0", description="UrbanNest Furnishings conversational shopping backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.workflow = workflow
    app.state.settings = settings

    def package_installed(distribution: str) -> bool:
        try:
            version(distribution)
            return True
        except PackageNotFoundError:
            return False

    def optional_user(authorization: str | None) -> dict | None:
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Use a Bearer access token.")
        user = store.get_user_for_token(token)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.")
        return user

    def signed_in_user(authorization: str | None) -> dict:
        user = optional_user(authorization)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in to use account preferences.")
        return user

    def session_for(requested_session: str, user: dict | None) -> str:
        return store.account_session_id(user["id"]) if user else requested_session

    @app.get("/health", tags=["system"])
    def health() -> dict:
        isolated_langflow = Path(__file__).resolve().parents[1] / ".langflow-venv" / "Scripts" / "langflow.exe"
        return {
            "status": "ok",
            "database": "sqlite",
            "ai_provider": settings.configured_provider,
            "workflow": settings.workflow_mode,
            "frameworks": {
                "langgraph": package_installed("langgraph"),
                "crewai": package_installed("crewai"),
                "autogen": package_installed("autogen-agentchat"),
                "langflow": package_installed("langflow") or isolated_langflow.exists(),
            },
        }

    @app.post("/auth/register", tags=["authentication"])
    def register(request: RegisterRequest) -> dict:
        try:
            user = store.create_user(request.name, request.email, request.password)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        token = store.create_auth_session(user["id"])
        return {"token": token, "user": user, "preferences": store.get_preferences(user["id"])}

    @app.post("/auth/login", tags=["authentication"])
    def login(request: LoginRequest) -> dict:
        user = store.authenticate_user(request.email, request.password)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")
        token = store.create_auth_session(user["id"])
        return {"token": token, "user": user, "preferences": store.get_preferences(user["id"])}

    @app.get("/auth/me", tags=["authentication"])
    def me(authorization: str | None = Header(default=None)) -> dict:
        user = signed_in_user(authorization)
        return {"user": user, "preferences": store.get_preferences(user["id"])}

    @app.post("/auth/logout", tags=["authentication"])
    def logout(authorization: str | None = Header(default=None)) -> dict:
        signed_in_user(authorization)
        _, _, token = (authorization or "").partition(" ")
        store.delete_auth_session(token)
        return {"status": "signed_out"}

    @app.get("/preferences", tags=["personalization"])
    def get_preferences(authorization: str | None = Header(default=None)) -> dict:
        user = signed_in_user(authorization)
        return store.get_preferences(user["id"])

    @app.put("/preferences", tags=["personalization"])
    def update_preferences(request: PreferencesRequest, authorization: str | None = Header(default=None)) -> dict:
        user = signed_in_user(authorization)
        return store.save_preferences(user["id"], request.model_dump())

    @app.get("/recommendations", tags=["personalization"])
    def recommendations(authorization: str | None = Header(default=None)) -> dict:
        user = signed_in_user(authorization)
        products = store.recommendations(user["id"])
        return {"products": products, "count": len(products)}

    @app.get("/search_products/", tags=["product tools"])
    def search_products(
        query: str = Query(default="", max_length=180),
        max_price: float | None = Query(default=None, gt=0),
        category: str | None = Query(default=None, max_length=80),
        limit: int = Query(default=12, ge=1, le=30),
    ) -> dict:
        products = store.search_products(query, max_price, category, limit)
        return {"products": products, "count": len(products), "query": query, "max_price": max_price}

    @app.get("/api/products", tags=["catalog"])
    def browse_products(category: str | None = None) -> dict:
        products = store.search_products("", category=category, limit=30)
        return {"products": products, "count": len(products)}

    @app.get("/get_cart_items/", tags=["cart tools"])
    def get_cart_items(session_id: str = Query(default="default", min_length=1, max_length=120), authorization: str | None = Header(default=None)) -> dict:
        return store.get_cart(session_for(session_id, optional_user(authorization)))

    @app.post("/add_product_to_cart/", tags=["cart tools"])
    def add_product_to_cart(request: AddProductRequest, authorization: str | None = Header(default=None)) -> dict:
        user = optional_user(authorization)
        product = store.get_product(request.product_id) if request.product_id else store.find_product(request.product_name or "")
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")
        try:
            outcome = store.add_to_cart(session_for(request.session_id, user), product["id"], request.quantity)
            if user:
                store.record_preference_event(user["id"], "cart_add", [product], 4)
            return outcome
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/update_product_in_cart/", tags=["cart tools"])
    def update_product_in_cart(request: UpdateCartRequest, authorization: str | None = Header(default=None)) -> dict:
        user = optional_user(authorization)
        try:
            return store.update_cart(session_for(request.session_id, user), request.quantity, request.cart_item_id, request.product_id, request.product_name)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/delete_product_from_cart/", tags=["cart tools"])
    def delete_product_from_cart(request: DeleteCartRequest, authorization: str | None = Header(default=None)) -> dict:
        user = optional_user(authorization)
        try:
            return store.delete_from_cart(session_for(request.session_id, user), request.cart_item_id, request.product_id, request.product_name)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/cart", tags=["cart"])
    def direct_cart_action(request: CartOperation, authorization: str | None = Header(default=None)) -> dict:
        user = optional_user(authorization)
        active_session = session_for(request.session_id, user)
        if request.action == "view":
            return store.get_cart(active_session)
        if request.action == "add":
            if request.product_id is None:
                raise HTTPException(status_code=422, detail="product_id is required to add an item.")
            outcome = store.add_to_cart(active_session, request.product_id, request.quantity or 1)
            if user:
                product = store.get_product(request.product_id)
                if product:
                    store.record_preference_event(user["id"], "cart_add", [product], 4)
            return outcome
        try:
            if request.action == "update":
                return store.update_cart(active_session, request.quantity or 1, product_id=request.product_id, product_name=request.product_name)
            return store.delete_from_cart(active_session, product_id=request.product_id, product_name=request.product_name)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/chat", tags=["assistant"])
    def chat(request: ChatRequest, authorization: str | None = Header(default=None)) -> dict:
        user = optional_user(authorization)
        result = workflow.run(request.message, session_for(request.session_id, user))
        if user:
            store.record_preference_event(user["id"], "search", result.get("products", []), 1)
            if result.get("intent") in {"add", "combined"}:
                cart_products = [store.get_product(item["product_id"]) for item in result.get("cart", {}).get("items", [])]
                store.record_preference_event(user["id"], "cart_add", [product for product in cart_products if product], 4)
            result["recommendations"] = store.recommendations(user["id"])
            result["authenticated"] = True
        return result

    return app


app = create_app()
