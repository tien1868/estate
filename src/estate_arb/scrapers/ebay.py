import logging
import re
from urllib.parse import quote_plus

from .base import BaseScraper
from ..models.ebay_listing import EbaySoldListing

logger = logging.getLogger(__name__)


class EbaySoldScraper(BaseScraper):
    """Scrapes eBay sold/completed listings for price data."""

    SEARCH_URL = "https://www.ebay.com/sch/i.html"

    async def search_sold(
        self, query: str, max_pages: int = 3
    ) -> list[EbaySoldListing]:
        """Search eBay for sold listings matching the query."""
        all_listings: list[EbaySoldListing] = []
        page = await self._new_page()

        try:
            for page_num in range(1, max_pages + 1):
                encoded_query = quote_plus(query)
                url = (
                    f"{self.SEARCH_URL}?_nkw={encoded_query}"
                    f"&_sacat=0&rt=nc&LH_Sold=1&LH_Complete=1&_pgn={page_num}"
                )

                await self._rate_limit()
                success = await self._safe_get(page, url, wait_selector=".srp-results")
                if not success:
                    logger.warning(f"Could not load eBay page {page_num} for '{query}'")
                    break

                # eBay uses li.s-card for listing cards
                items = await page.query_selector_all("li.s-card")
                page_count = 0
                for item_el in items:
                    listing = await self._parse_listing(item_el)
                    if listing:
                        all_listings.append(listing)
                        page_count += 1

                logger.info(
                    f"eBay page {page_num}: {page_count} listings for '{query}'"
                )

                # Stop if we got fewer results than expected (last page)
                if page_count < 10:
                    break
        finally:
            await page.close()

        return all_listings

    async def _parse_listing(self, element) -> EbaySoldListing | None:
        """Parse a single sold listing element (li.s-card) from eBay search results."""
        try:
            # Extract all data from the card via a single JS evaluation
            data = await element.evaluate("""el => {
                const title_el = el.querySelector('.s-card__title');
                const title = title_el ? title_el.innerText.trim() : '';

                // Find all spans and extract relevant text
                const spans = el.querySelectorAll('span');
                let price = '', sold_date = '', condition = '', shipping = '';
                for (const s of spans) {
                    const t = s.innerText.trim();
                    if (!price && t.startsWith('$') && !t.includes('delivery'))
                        price = t;
                    else if (!sold_date && t.startsWith('Sold '))
                        sold_date = t;
                    else if (!condition && (t === 'Pre-Owned' || t === 'Brand New' || t === 'New' || t === 'Refurbished' || t.startsWith('Open box') || t === 'For parts or not working'))
                        condition = t;
                    else if (!shipping && (t.includes('delivery') || t.includes('shipping')))
                        shipping = t;
                }

                const link_el = el.querySelector('a.s-card__link');
                const url = link_el ? link_el.href : '';

                return {title, price, sold_date, condition, shipping, url};
            }""")

            title = data.get("title", "")
            # Clean up "Opens in a new window or tab" suffix
            title = re.sub(r"\s*Opens in a new window or tab\s*$", "", title)

            # Skip placeholder items
            if not title or title.lower().startswith("shop on ebay"):
                return None

            price = self._parse_price(data.get("price", ""))
            if price is None:
                return None

            sold_date = data.get("sold_date", "")
            # Only include items that were actually sold
            if not sold_date:
                return None
            sold_date = re.sub(r"^Sold\s+", "", sold_date)

            shipping = self._parse_shipping(data.get("shipping", ""))

            return EbaySoldListing(
                title=title,
                sold_price=price,
                sold_date=sold_date,
                condition=data.get("condition", ""),
                url=data.get("url", ""),
                shipping_cost=shipping,
            )
        except Exception as e:
            logger.debug(f"Failed to parse listing element: {e}")
            return None

    @staticmethod
    def _parse_price(price_text: str) -> float | None:
        """Parse eBay price text into a float. Handles ranges by averaging."""
        cleaned = price_text.replace("$", "").replace(",", "").strip()

        # Handle range: "$10.00 to $25.00"
        if " to " in cleaned:
            parts = cleaned.split(" to ")
            try:
                low = float(parts[0].strip())
                high = float(parts[1].strip())
                return (low + high) / 2
            except (ValueError, IndexError):
                return None

        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _parse_shipping(ship_text: str) -> float:
        """Parse shipping cost text. Returns 0.0 for free shipping."""
        lower = ship_text.lower()
        if "free" in lower:
            return 0.0

        match = re.search(r"\$(\d+(?:\.\d{2})?)", ship_text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return 0.0
