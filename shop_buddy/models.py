"""Pydantic schemas shared by the public API."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AddProductRequest(BaseModel):
    product_id: int | None = None
    product_name: str | None = Field(default=None, max_length=180)
    quantity: int = Field(default=1, ge=1, le=99)
    session_id: str = Field(default="default", min_length=1, max_length=120)

    @model_validator(mode="after")
    def has_product_reference(self):
        if self.product_id is None and not self.product_name:
            raise ValueError("Provide product_id or product_name.")
        return self


class UpdateCartRequest(BaseModel):
    cart_item_id: int | None = None
    product_id: int | None = None
    product_name: str | None = Field(default=None, max_length=180)
    quantity: int = Field(ge=1, le=99)
    session_id: str = Field(default="default", min_length=1, max_length=120)

    @model_validator(mode="after")
    def has_cart_reference(self):
        if self.cart_item_id is None and self.product_id is None and not self.product_name:
            raise ValueError("Provide cart_item_id, product_id, or product_name.")
        return self


class DeleteCartRequest(BaseModel):
    cart_item_id: int | None = None
    product_id: int | None = None
    product_name: str | None = Field(default=None, max_length=180)
    session_id: str = Field(default="default", min_length=1, max_length=120)

    @model_validator(mode="after")
    def has_cart_reference(self):
        if self.cart_item_id is None and self.product_id is None and not self.product_name:
            raise ValueError("Provide cart_item_id, product_id, or product_name.")
        return self


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(default="default", min_length=1, max_length=120)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class PreferencesRequest(BaseModel):
    favorite_categories: list[str] = Field(default_factory=list, max_length=8)
    favorite_colors: list[str] = Field(default_factory=list, max_length=8)
    room: str = Field(default="", max_length=80)
    budget: float | None = Field(default=None, gt=0, le=100000)

    @model_validator(mode="after")
    def normalize_lists(self):
        self.favorite_categories = [item.strip() for item in self.favorite_categories if item.strip()][:8]
        self.favorite_colors = [item.strip() for item in self.favorite_colors if item.strip()][:8]
        self.room = self.room.strip()
        return self


class CartOperation(BaseModel):
    action: Literal["add", "update", "delete", "view"]
    product_id: int | None = None
    product_name: str | None = None
    quantity: int | None = Field(default=None, ge=1, le=99)
    session_id: str = "default"

