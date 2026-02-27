import re

from ..config import BrandConfig
from ..models.estate_sale import EstateSale, SaleItem


class BrandMatcher:
    """Match brand names against estate sale descriptions using regex."""

    def __init__(self, brands: list[BrandConfig]):
        self.brands = brands
        # Pre-compile regex patterns for each brand's search terms
        self._patterns: dict[str, list[re.Pattern]] = {}
        for brand in brands:
            patterns = []
            for term in brand.search_terms:
                pattern = re.compile(
                    r"\b" + re.escape(term) + r"\b", re.IGNORECASE
                )
                patterns.append(pattern)
            self._patterns[brand.name] = patterns

    def match_sale(self, sale: EstateSale) -> list[SaleItem]:
        """Find all brand matches in a sale's description."""
        text = sale.description
        if not text:
            return []

        matched_items = []

        for brand in self.brands:
            for pattern in self._patterns[brand.name]:
                match = pattern.search(text)
                if match:
                    # Extract context around the match
                    start = max(0, match.start() - 100)
                    end = min(len(text), match.end() + 100)
                    context = text[start:end].strip()

                    item = SaleItem(
                        brand=brand.name,
                        description=context,
                        estimated_price=self._extract_price_near_match(text, match),
                        confidence=1.0,
                        source="text",
                    )
                    matched_items.append(item)
                    break  # One match per brand per sale

        return matched_items

    @staticmethod
    def _extract_price_near_match(text: str, match: re.Match) -> float | None:
        """Try to find a dollar amount near the brand mention."""
        region_start = max(0, match.start() - 200)
        region_end = min(len(text), match.end() + 200)
        region = text[region_start:region_end]

        price_pattern = re.compile(r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)")
        price_match = price_pattern.search(region)
        if price_match:
            price_str = price_match.group(1).replace(",", "")
            try:
                return float(price_str)
            except ValueError:
                return None
        return None
