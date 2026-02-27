from dataclasses import dataclass, field


@dataclass
class ArbitrageOpportunity:
    """A potential arbitrage opportunity combining estate sale + eBay data."""
    estate_sale_title: str
    estate_sale_url: str
    estate_sale_dates: list[str]
    estate_sale_location: str
    matched_brand: str
    matched_description: str
    detection_source: str  # "text", "vision", or "both"
    estate_price_estimate: float | None = None
    ebay_median_sold: float = 0.0
    ebay_average_sold: float = 0.0
    ebay_sample_count: int = 0
    ebay_price_range: tuple[float, float] = (0.0, 0.0)
    profit_multiplier: float | None = None
    photo_urls: list[str] = field(default_factory=list)
    item_type: str = ""
    vision_reasoning: str = ""

    @property
    def estimated_roi_pct(self) -> float | None:
        if self.estate_price_estimate and self.estate_price_estimate > 0:
            return (
                (self.ebay_median_sold - self.estate_price_estimate)
                / self.estate_price_estimate
                * 100
            )
        return None
