import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BrandConfig:
    name: str
    category: str
    search_terms: list[str]
    ebay_search_suffix: str = ""
    min_ebay_price: float = 10


@dataclass
class Settings:
    zip_code: str = "10001"
    radius_miles: int = 30
    min_profit_multiplier: float = 2.0
    max_ebay_pages: int = 3
    max_estate_sales: int = 50
    max_photos_per_sale: int = 30
    cache_ttl_hours: float = 24
    request_delay_seconds: float = 2.0
    ebay_request_delay_seconds: float = 3.0
    headless_browser: bool = True
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )


def load_brands(path: str = "config/brands.json") -> list[BrandConfig]:
    """Load brand configurations from JSON file."""
    filepath = Path(path)
    if not filepath.exists():
        raise FileNotFoundError(f"Brands config not found: {filepath}")

    with open(filepath) as f:
        data = json.load(f)

    brands = []
    for entry in data["brands"]:
        brands.append(
            BrandConfig(
                name=entry["name"],
                category=entry["category"],
                search_terms=entry["search_terms"],
                ebay_search_suffix=entry.get("ebay_search_suffix", ""),
                min_ebay_price=entry.get("min_ebay_price", 10),
            )
        )
    return brands


def load_settings(path: str = "config/settings.json") -> Settings:
    """Load application settings from JSON file."""
    filepath = Path(path)
    if not filepath.exists():
        return Settings()

    with open(filepath) as f:
        data = json.load(f)

    return Settings(**{k: v for k, v in data.items() if hasattr(Settings, k)})
