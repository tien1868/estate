from dataclasses import dataclass, field


@dataclass
class SaleItem:
    """An item detected within an estate sale (from text or photo analysis)."""
    brand: str
    description: str
    estimated_price: float | None = None
    photo_urls: list[str] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "text"  # "text" or "vision"
    item_type: str = ""   # e.g. "jacket", "sweater", "cookware"
    reasoning: str = ""   # vision model's explanation of why this is valuable
    ebay_query: str = ""  # short eBay search query from vision model


@dataclass
class EstateSale:
    """An estate sale listing from EstateSales.net."""
    sale_id: str
    title: str
    organizer: str
    address: str
    city: str
    state: str
    zip_code: str
    url: str
    dates: list[str] = field(default_factory=list)
    description: str = ""
    photo_urls: list[str] = field(default_factory=list)
    photo_count: int = 0
    matched_items: list[SaleItem] = field(default_factory=list)
    distance_miles: float | None = None
    is_online: bool = False
