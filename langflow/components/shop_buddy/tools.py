"""Five LangFlow Tool Mode components backed by the Shop Buddy FastAPI API."""
from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec

import requests

_sdk_root = "lfx" if find_spec("lfx") is not None else "langflow"
_custom = import_module(f"{_sdk_root}.custom")
_io = import_module(f"{_sdk_root}.io")
_schema = import_module(f"{_sdk_root}.schema")
Component = _custom.Component
FloatInput = _io.FloatInput
IntInput = _io.IntInput
Output = _io.Output
StrInput = _io.StrInput
Data = _schema.Data


def _api_url_input() -> StrInput:
    return StrInput(
        name="api_url",
        display_name="Shop Buddy API URL",
        value="http://127.0.0.1:8000",
        advanced=True,
    )


def _tool_output() -> Output:
    return Output(display_name="Structured API Response", name="result", method="run_tool")


def _structured(response: requests.Response) -> Data:
    response.raise_for_status()
    payload = response.json()
    return Data(data=payload if isinstance(payload, dict) else {"result": payload})


class SearchProductsComponent(Component):
    display_name = "Search Products"
    description = "Semantically search UrbanNest products through FastAPI."
    name = "SearchProducts"
    icon = "ShoppingCart"
    trace_type = "tool"
    inputs = [
        _api_url_input(),
        StrInput(name="query", display_name="Product Requirements", tool_mode=True),
        FloatInput(name="max_price", display_name="Maximum Price", required=False, tool_mode=True),
    ]
    outputs = [_tool_output()]

    def run_tool(self) -> Data:
        params = {"query": self.query}
        if self.max_price:
            params["max_price"] = self.max_price
        return _structured(requests.get(f"{self.api_url.rstrip('/')}/search_products/", params=params, timeout=15))


class AddProductToCartComponent(Component):
    display_name = "AddProductToCart"
    description = "Add a catalogue product to the active shopping cart."
    name = "AddProductToCart"
    icon = "ShoppingCart"
    trace_type = "tool"
    inputs = [
        _api_url_input(),
        IntInput(name="product_id", display_name="Product ID", tool_mode=True),
        IntInput(name="quantity", display_name="Quantity", value=1, tool_mode=True),
        StrInput(name="session_id", display_name="Session ID", value="default", tool_mode=True),
    ]
    outputs = [_tool_output()]

    def run_tool(self) -> Data:
        payload = {"product_id": self.product_id, "quantity": self.quantity, "session_id": self.session_id}
        return _structured(requests.post(f"{self.api_url.rstrip('/')}/add_product_to_cart/", json=payload, timeout=15))


class UpdateCartItemComponent(Component):
    display_name = "UpdateCartItem"
    description = "Set the quantity of a product already in the shopping cart."
    name = "UpdateCartItem"
    icon = "ShoppingCart"
    trace_type = "tool"
    inputs = [
        _api_url_input(),
        IntInput(name="product_id", display_name="Product ID", tool_mode=True),
        IntInput(name="quantity", display_name="New Quantity", value=1, tool_mode=True),
        StrInput(name="session_id", display_name="Session ID", value="default", tool_mode=True),
    ]
    outputs = [_tool_output()]

    def run_tool(self) -> Data:
        payload = {"product_id": self.product_id, "quantity": self.quantity, "session_id": self.session_id}
        return _structured(requests.put(f"{self.api_url.rstrip('/')}/update_product_in_cart/", json=payload, timeout=15))


class DeleteCartItemComponent(Component):
    display_name = "DeleteCartItem"
    description = "Remove a catalogue product from the shopping cart."
    name = "DeleteCartItem"
    icon = "ShoppingCart"
    trace_type = "tool"
    inputs = [
        _api_url_input(),
        IntInput(name="product_id", display_name="Product ID", tool_mode=True),
        StrInput(name="session_id", display_name="Session ID", value="default", tool_mode=True),
    ]
    outputs = [_tool_output()]

    def run_tool(self) -> Data:
        payload = {"product_id": self.product_id, "session_id": self.session_id}
        return _structured(requests.delete(f"{self.api_url.rstrip('/')}/delete_product_from_cart/", json=payload, timeout=15))


class GetCartItemsComponent(Component):
    display_name = "GetCartItems"
    description = "Retrieve the current shopping cart and calculated total."
    name = "GetCartItems"
    icon = "ShoppingCart"
    trace_type = "tool"
    inputs = [
        _api_url_input(),
        StrInput(name="session_id", display_name="Session ID", value="default", tool_mode=True),
    ]
    outputs = [_tool_output()]

    def run_tool(self) -> Data:
        return _structured(requests.get(
            f"{self.api_url.rstrip('/')}/get_cart_items/",
            params={"session_id": self.session_id},
            timeout=15,
        ))
