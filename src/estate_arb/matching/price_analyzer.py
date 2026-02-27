import statistics

from ..models.ebay_listing import EbaySoldListing


class PriceAnalyzer:
    """Compute price statistics from eBay sold listings."""

    @staticmethod
    def analyze(listings: list[EbaySoldListing]) -> dict:
        if not listings:
            return {
                "count": 0,
                "median": 0.0,
                "average": 0.0,
                "min": 0.0,
                "max": 0.0,
            }

        prices = [listing.sold_price for listing in listings]

        # Remove outliers beyond 2 standard deviations (if enough data)
        if len(prices) >= 5:
            mean = statistics.mean(prices)
            stdev = statistics.stdev(prices)
            if stdev > 0:
                prices = [p for p in prices if abs(p - mean) <= 2 * stdev]
                # Ensure we still have data after filtering
                if not prices:
                    prices = [listing.sold_price for listing in listings]

        return {
            "count": len(prices),
            "median": round(statistics.median(prices), 2),
            "average": round(statistics.mean(prices), 2),
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
        }
