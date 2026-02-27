from dataclasses import dataclass


@dataclass
class EbaySoldListing:
    """A single sold listing from eBay."""
    title: str
    sold_price: float
    sold_date: str = ""
    condition: str = ""
    url: str = ""
    shipping_cost: float = 0.0

    @property
    def total_price(self) -> float:
        return self.sold_price + self.shipping_cost
