"""SQLite catalogue, cart, and conversation persistence."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any, Iterator


SEED_PRODUCTS = [
    ("CH-101", "AeroMesh Office Chair", "Office Chairs", 289.00, "Breathable ergonomic chair with adjustable lumbar support.", 18, 4.8, "Mesh", "Graphite"),
    ("CH-102", "Cedar Executive Chair", "Office Chairs", 449.00, "Premium cushioned executive chair with walnut arms.", 8, 4.7, "Leatherette", "Cognac"),
    ("CH-103", "Pace Task Chair", "Office Chairs", 179.00, "Compact adjustable task chair for focused home offices.", 25, 4.5, "Fabric", "Cloud Grey"),
    ("CH-104", "Forum Conference Chair", "Conference Seating", 219.00, "Stackable upholstered meeting chair with slim steel frame.", 30, 4.6, "Fabric", "Navy"),
    ("CH-105", "Forum Conference Chair, Set of 2", "Conference Seating", 399.00, "Two refined conference chairs designed for long meetings.", 15, 4.7, "Fabric", "Sand"),
    ("DS-201", "Atlas Standing Desk", "Desks", 699.00, "Electric sit-stand desk with memory controls and cable tray.", 9, 4.9, "Bamboo", "Natural"),
    ("DS-202", "Harbor Writing Desk", "Desks", 349.00, "Small-space writing desk with two soft-close drawers.", 14, 4.6, "Oak veneer", "White Oak"),
    ("DS-203", "Milo Compact Desk", "Desks", 249.00, "Simple compact desk made for apartments and study corners.", 21, 4.4, "Steel and MDF", "Black"),
    ("TB-301", "Cove Coffee Table", "Tables", 329.00, "Rounded oak coffee table with a lower display shelf.", 11, 4.8, "Oak", "Honey"),
    ("TB-302", "Linea Dining Table", "Tables", 799.00, "Extendable six-seat dining table with a durable ceramic top.", 6, 4.9, "Ceramic", "Stone"),
    ("SF-401", "Haven Two-Seat Sofa", "Sofas", 999.00, "Deep, supportive two-seat sofa in performance weave.", 5, 4.8, "Performance fabric", "Moss"),
    ("SF-402", "Loft Modular Sofa", "Sofas", 1499.00, "Configurable modular sofa with reversible chaise.", 4, 4.9, "Performance fabric", "Oat"),
    ("ST-501", "Arc Floor Lamp", "Lighting", 159.00, "Dimmable floor lamp with a warm, focused reading light.", 32, 4.5, "Metal", "Brass"),
    ("ST-502", "Ember Desk Lamp", "Lighting", 89.00, "Compact LED desk lamp with three color temperatures.", 40, 4.6, "Aluminum", "Matte Black"),
    ("AC-601", "Wool Desk Pad", "Accessories", 59.00, "Soft wool-blend desk pad that protects surfaces and reduces glare.", 50, 4.7, "Wool blend", "Charcoal"),
    ("AC-602", "Cable Tidy Set", "Accessories", 29.00, "Six reusable cable organizers for a calm, tidy workspace.", 60, 4.4, "Silicone", "Slate"),
]


class ShopStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL,
                    price REAL NOT NULL, description TEXT NOT NULL, stock INTEGER NOT NULL,
                    rating REAL NOT NULL, material TEXT NOT NULL, color TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cart_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    product_id INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, product_id),
                    FOREIGN KEY(product_id) REFERENCES products(id)
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY, messages_json TEXT NOT NULL DEFAULT '[]',
                    last_results_json TEXT NOT NULL DEFAULT '[]', selected_product_id INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER PRIMARY KEY, favorite_categories_json TEXT NOT NULL DEFAULT '[]',
                    favorite_colors_json TEXT NOT NULL DEFAULT '[]', room TEXT NOT NULL DEFAULT '',
                    budget REAL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS preference_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL, product_id INTEGER, category TEXT,
                    weight REAL NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(product_id) REFERENCES products(id)
                );
            """)
            count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            if count == 0:
                conn.executemany("""
                    INSERT INTO products (sku, title, category, price, description, stock, rating, material, color)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, SEED_PRODUCTS)

    @staticmethod
    def _as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def search_products(self, query: str = "", max_price: float | None = None, category: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        clauses, params = ["stock > 0"], []
        if max_price is not None:
            clauses.append("price <= ?")
            params.append(max_price)
        if category:
            clauses.append("LOWER(category) LIKE ?")
            params.append(f"%{category.lower()}%")
        sql = f"SELECT * FROM products WHERE {' AND '.join(clauses)}"
        with self.connection() as conn:
            products = [dict(row) for row in conn.execute(sql, params).fetchall()]

        words = [word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2]
        # Requirements such as "affordable", "warm", and "small" describe
        # ranking preferences rather than mandatory literal catalogue terms.
        soft_terms = {"affordable", "budget", "cheap", "premium", "warm", "cozy", "small", "compact", "home", "modern"}
        semantic_groups = {
            "chair": {"chair", "chairs", "seating"},
            "chairs": {"chair", "chairs", "seating"},
            "seating": {"chair", "chairs", "seating"},
            "desk": {"desk", "desks", "workstation", "workspace", "writing"},
            "desks": {"desk", "desks", "workstation", "workspace", "writing"},
            "sofa": {"sofa", "sofas", "couch", "sectional"},
            "couch": {"sofa", "sofas", "couch", "sectional"},
            "lamp": {"lamp", "lamps", "lighting", "light"},
            "light": {"lamp", "lamps", "lighting", "light"},
            "table": {"table", "tables", "dining", "coffee"},
            "pad": {"pad", "mat", "protector"},
        }
        required = [word for word in words if word not in soft_terms]

        def relevance(product: dict[str, Any]) -> tuple[float, int, float]:
            title = product["title"].lower()
            product_category = product["category"].lower()
            description = product["description"].lower()
            details = f"{product['material']} {product['color']}".lower()
            score = 0.0
            identity_score = 0.0
            matched_terms = 0
            for word in required:
                variants = semantic_groups.get(word, {word, word.rstrip("s")})
                identity_term_score = max(
                    (6 if variant in title else 0) + (5 if variant in product_category else 0)
                    for variant in variants
                )
                term_score = max(
                    (6 if variant in title else 0)
                    + (5 if variant in product_category else 0)
                    + (2 if variant in description else 0)
                    + (1 if variant in details else 0)
                    for variant in variants
                )
                score += term_score
                identity_score += identity_term_score
                # A semantic term counts as satisfied only when it appears in
                # the product identity (title/category), not merely in prose.
                matched_terms += int(term_score >= 5)
            if "affordable" in words or "budget" in words or "cheap" in words:
                score += max(0, 3 - product["price"] / 250)
            if "small" in words or "compact" in words:
                score += 2 if "compact" in description or "small" in description else 0
            return score, matched_terms, identity_score

        if required:
            ranked = [(relevance(product), product) for product in products]
            full_matches = [item for item in ranked if item[0][1] == len(required)]
            candidates = full_matches or [item for item in ranked if item[0][0] > 0]
            if full_matches:
                if len(required) == 1:
                    strongest_identity = max(item[0][2] for item in candidates)
                    candidates = [item for item in candidates if item[0][2] >= strongest_identity - 1]
                candidates.sort(key=lambda item: (-item[0][2], -item[1]["rating"], item[1]["price"]))
            else:
                candidates.sort(key=lambda item: (-item[0][0], -item[1]["rating"], item[1]["price"]))
            products = [product for _, product in candidates]
        else:
            products.sort(key=lambda product: (-product["rating"], product["price"]))
        return products[:max(1, min(limit, 30))]

    def get_product(self, product_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            return self._as_dict(conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone())

    def find_product(self, product_name: str) -> dict[str, Any] | None:
        matches = self.search_products(product_name, limit=1)
        return matches[0] if matches else None

    def get_cart(self, session_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            rows = conn.execute("""
                SELECT c.id AS cart_item_id, c.quantity, p.id AS product_id, p.sku, p.title,
                       p.category, p.price AS unit_price, p.color, p.stock,
                       ROUND(c.quantity * p.price, 2) AS subtotal
                FROM cart_items c JOIN products p ON p.id = c.product_id
                WHERE c.session_id = ? ORDER BY c.created_at DESC
            """, (session_id,)).fetchall()
        items = [dict(row) for row in rows]
        return {"items": items, "item_count": sum(item["quantity"] for item in items), "total": round(sum(item["subtotal"] for item in items), 2)}

    def add_to_cart(self, session_id: str, product_id: int, quantity: int) -> dict[str, Any]:
        product = self.get_product(product_id)
        if not product:
            raise LookupError("That product could not be found.")
        with self.connection() as conn:
            existing = conn.execute("SELECT id, quantity FROM cart_items WHERE session_id = ? AND product_id = ?", (session_id, product_id)).fetchone()
            new_quantity = quantity + (existing["quantity"] if existing else 0)
            if new_quantity > product["stock"]:
                raise ValueError(f"Only {product['stock']} units of {product['title']} are available.")
            if existing:
                conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (new_quantity, existing["id"]))
            else:
                conn.execute("INSERT INTO cart_items (session_id, product_id, quantity) VALUES (?, ?, ?)", (session_id, product_id, quantity))
        return {"product": product, "quantity": new_quantity, "cart": self.get_cart(session_id)}

    def _cart_row(self, conn: sqlite3.Connection, session_id: str, cart_item_id: int | None, product_id: int | None, product_name: str | None) -> sqlite3.Row | None:
        base = "SELECT c.id, c.product_id, c.quantity, p.title, p.category, p.stock FROM cart_items c JOIN products p ON p.id=c.product_id WHERE c.session_id = ?"
        params: list[Any] = [session_id]
        if cart_item_id is not None:
            return conn.execute(base + " AND c.id = ?", params + [cart_item_id]).fetchone()
        if product_id is not None:
            return conn.execute(base + " AND c.product_id = ?", params + [product_id]).fetchone()
        if product_name:
            rows = conn.execute(base, params).fetchall()
            words = [word.rstrip("s") for word in re.findall(r"[a-z0-9]+", product_name.lower()) if len(word) > 2]
            for row in rows:
                searchable = f"{row['title']} {row['category']}".lower()
                if words and all(word in searchable for word in words):
                    return row
            return None
        return None

    def update_cart(self, session_id: str, quantity: int, cart_item_id: int | None = None, product_id: int | None = None, product_name: str | None = None) -> dict[str, Any]:
        with self.connection() as conn:
            row = self._cart_row(conn, session_id, cart_item_id, product_id, product_name)
            if not row:
                raise LookupError("That item is not in this cart.")
            if quantity > row["stock"]:
                raise ValueError(f"Only {row['stock']} units of {row['title']} are available.")
            conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (quantity, row["id"]))
            title = row["title"]
        return {"title": title, "quantity": quantity, "cart": self.get_cart(session_id)}

    def delete_from_cart(self, session_id: str, cart_item_id: int | None = None, product_id: int | None = None, product_name: str | None = None) -> dict[str, Any]:
        with self.connection() as conn:
            row = self._cart_row(conn, session_id, cart_item_id, product_id, product_name)
            if not row:
                raise LookupError("That item is not in this cart.")
            conn.execute("DELETE FROM cart_items WHERE id = ?", (row["id"],))
            title = row["title"]
        return {"title": title, "cart": self.get_cart(session_id)}

    def load_memory(self, session_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return {"messages": [], "last_results": [], "selected_product_id": None}
        return {"messages": json.loads(row["messages_json"]), "last_results": json.loads(row["last_results_json"]), "selected_product_id": row["selected_product_id"]}

    def save_memory(self, session_id: str, messages: list[dict[str, str]], last_results: list[dict[str, Any]], selected_product_id: int | None) -> None:
        with self.connection() as conn:
            conn.execute("""
                INSERT INTO conversations (session_id, messages_json, last_results_json, selected_product_id, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET messages_json=excluded.messages_json,
                    last_results_json=excluded.last_results_json, selected_product_id=excluded.selected_product_id,
                    updated_at=CURRENT_TIMESTAMP
            """, (session_id, json.dumps(messages[-20:]), json.dumps(last_results[:12]), selected_product_id))

    @staticmethod
    def _public_user(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "email": row["email"], "created_at": row["created_at"]}

    @staticmethod
    def _password_hash(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000).hex()

    def create_user(self, name: str, email: str, password: str) -> dict[str, Any]:
        normalized_email = email.strip().lower()
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt)
        try:
            with self.connection() as conn:
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password_hash, password_salt) VALUES (?, ?, ?, ?)",
                    (name.strip(), normalized_email, password_hash, salt.hex()),
                )
                user_id = cursor.lastrowid
                conn.execute("INSERT INTO user_preferences (user_id) VALUES (?)", (user_id,))
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._public_user(row)
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account already exists for that email address.") from exc

    def authenticate_user(self, email: str, password: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if not row:
            return None
        calculated = self._password_hash(password, bytes.fromhex(row["password_salt"]))
        if not secrets.compare_digest(calculated, row["password_hash"]):
            return None
        return self._public_user(row)

    def create_auth_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(40)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        with self.connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
            conn.execute("INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)", (token_hash, user_id, expires_at))
        return token

    def get_user_for_token(self, token: str) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute("""
                SELECT u.* FROM auth_sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
            """, (token_hash, now)).fetchone()
        return self._public_user(row) if row else None

    def delete_auth_session(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))

    @staticmethod
    def account_session_id(user_id: int) -> str:
        return f"account:{user_id}"

    def get_preferences(self, user_id: int) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return {"favorite_categories": [], "favorite_colors": [], "room": "", "budget": None}
        return {
            "favorite_categories": json.loads(row["favorite_categories_json"]),
            "favorite_colors": json.loads(row["favorite_colors_json"]),
            "room": row["room"],
            "budget": row["budget"],
        }

    def save_preferences(self, user_id: int, preferences: dict[str, Any]) -> dict[str, Any]:
        favorite_categories = preferences.get("favorite_categories", [])
        favorite_colors = preferences.get("favorite_colors", [])
        with self.connection() as conn:
            conn.execute("""
                INSERT INTO user_preferences (user_id, favorite_categories_json, favorite_colors_json, room, budget, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET favorite_categories_json=excluded.favorite_categories_json,
                    favorite_colors_json=excluded.favorite_colors_json, room=excluded.room, budget=excluded.budget,
                    updated_at=CURRENT_TIMESTAMP
            """, (user_id, json.dumps(favorite_categories), json.dumps(favorite_colors), preferences.get("room", ""), preferences.get("budget")))
        return self.get_preferences(user_id)

    def record_preference_event(self, user_id: int, event_type: str, products: list[dict[str, Any]], weight: float) -> None:
        rows = [(user_id, event_type, product.get("id"), product.get("category"), weight) for product in products[:8]]
        if not rows:
            return
        with self.connection() as conn:
            conn.executemany("INSERT INTO preference_events (user_id, event_type, product_id, category, weight) VALUES (?, ?, ?, ?, ?)", rows)

    def recommendations(self, user_id: int, limit: int = 4) -> list[dict[str, Any]]:
        preferences = self.get_preferences(user_id)
        category_scores = {category.lower(): 5.0 for category in preferences["favorite_categories"]}
        color_scores = {color.lower(): 2.0 for color in preferences["favorite_colors"]}
        with self.connection() as conn:
            events = conn.execute("SELECT category, SUM(weight) AS score FROM preference_events WHERE user_id = ? GROUP BY category", (user_id,)).fetchall()
        for event in events:
            if event["category"]:
                key = event["category"].lower()
                category_scores[key] = category_scores.get(key, 0) + float(event["score"])
        candidates = self.search_products("", max_price=preferences["budget"], limit=30)
        candidates.sort(key=lambda product: (
            category_scores.get(product["category"].lower(), 0) + color_scores.get(product["color"].lower(), 0),
            product["rating"],
            -product["price"],
        ), reverse=True)
        return candidates[:limit]
