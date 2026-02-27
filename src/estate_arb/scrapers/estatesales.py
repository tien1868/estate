import asyncio
import json
import logging
import re
from urllib.parse import urljoin

from .base import BaseScraper
from ..models.estate_sale import EstateSale

logger = logging.getLogger(__name__)


class EstateSalesScraper(BaseScraper):
    """Scrapes EstateSales.net for upcoming estate sales near a location.

    The site is an Angular app that requires JS rendering. We use two strategies:
    1. Primary: intercept the XHR/API responses the Angular app fetches (most reliable)
    2. Fallback: parse the rendered DOM directly
    """

    BASE_URL = "https://www.estatesales.net"

    async def search_sales(
        self,
        zip_code: str,
        state: str = "",
        city: str = "",
        max_sales: int = 50,
    ) -> list[EstateSale]:
        """Find estate sales near the given location.

        Args:
            zip_code: ZIP code to search near
            state: State abbreviation (e.g., "NJ"). If empty, uses ZIP-based URL.
            city: City name (e.g., "Montclair"). If empty, uses ZIP-based URL.
            max_sales: Maximum number of sales to return
        """
        page = await self._new_page()
        sales: list[EstateSale] = []
        api_data: list[dict] = []

        # Intercept XHR responses to capture the sale data as JSON
        async def handle_response(response):
            try:
                url = response.url
                if "/api/" in url and response.status == 200:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        if isinstance(body, list) and body:
                            # Check if this looks like sale data
                            first = body[0] if body else {}
                            if any(
                                k in first
                                for k in ("saleId", "id", "title", "name", "address")
                            ):
                                api_data.extend(body)
                                logger.info(
                                    f"Intercepted API response with {len(body)} items"
                                )
                        elif isinstance(body, dict) and "sales" in body:
                            api_data.extend(body["sales"])
                            logger.info(
                                f"Intercepted API response with {len(body['sales'])} sales"
                            )
            except Exception:
                pass

        page.on("response", handle_response)

        # Build URL
        if state and city:
            url = f"{self.BASE_URL}/{state}/{city}/{zip_code}"
        else:
            url = f"{self.BASE_URL}/companies/zip/{zip_code}"

        try:
            logger.info(f"Loading estate sales page: {url}")
            success = await self._safe_get(page, url)
            if not success:
                logger.error(f"Failed to load {url}")
                return []

            # Wait for content to render
            await asyncio.sleep(3)

            # Scroll down to trigger lazy loading of more sales
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            # Strategy 1: use intercepted API data if available
            if api_data:
                logger.info(f"Using {len(api_data)} sales from intercepted API data")
                for item in api_data[:max_sales]:
                    sale = self._parse_api_sale(item)
                    if sale:
                        sales.append(sale)
            else:
                # Strategy 2: parse the rendered DOM
                logger.info("No API data intercepted, falling back to DOM parsing")
                sales = await self._parse_dom_sales(page, max_sales)

        finally:
            await page.close()

        logger.info(f"Found {len(sales)} estate sales near {zip_code}")
        return sales

    def _parse_api_sale(self, data: dict) -> EstateSale | None:
        """Parse a sale from intercepted API JSON data."""
        try:
            sale_id = str(
                data.get("saleId", data.get("id", data.get("sale_id", "")))
            )
            if not sale_id:
                return None

            title = data.get("title", data.get("name", ""))
            organizer = data.get(
                "orgName",
                data.get("companyName", data.get("organizer", "")),
            )
            address = data.get("address", data.get("street", ""))
            city = data.get("city", data.get("cityName", ""))
            state = data.get("state", data.get("stateCode", data.get("stateAbbreviation", "")))
            zip_code = str(data.get("zipCode", data.get("postalCodeNumber", data.get("zip", ""))))

            # Build URL — the Angular app needs /{STATE}/{City}/{ZIP}/{id} format
            url_path = data.get("url", data.get("saleUrl", ""))
            if url_path and not url_path.startswith("http"):
                url = f"{self.BASE_URL}{url_path}"
            elif url_path:
                url = url_path
            elif state and city and zip_code:
                url = f"{self.BASE_URL}/{state}/{city}/{zip_code}/{sale_id}"
            else:
                url = f"{self.BASE_URL}/estate-sales/{sale_id}"

            # Dates
            dates = []
            if "dates" in data and isinstance(data["dates"], list):
                for d in data["dates"]:
                    if isinstance(d, str):
                        dates.append(d)
                    elif isinstance(d, dict):
                        dates.append(d.get("formattedDate", d.get("date", str(d))))
            elif "dateRange" in data:
                dates.append(str(data["dateRange"]))

            # Description
            description = data.get("description", data.get("details", ""))
            # Strip HTML tags if present
            if description:
                description = re.sub(r"<[^>]+>", " ", description)
                description = re.sub(r"\s+", " ", description).strip()

            # Photos
            photo_urls = []
            photo_count = data.get("pictureCount", data.get("photoCount", 0))
            if "pictures" in data and isinstance(data["pictures"], list):
                for pic in data["pictures"]:
                    if isinstance(pic, str):
                        photo_urls.append(pic)
                    elif isinstance(pic, dict):
                        pic_url = pic.get("url", pic.get("imageUrl", ""))
                        if pic_url:
                            photo_urls.append(pic_url)

            # Distance
            distance = data.get("distance", data.get("distanceMiles", None))
            if distance is not None:
                try:
                    distance = float(distance)
                except (ValueError, TypeError):
                    distance = None

            return EstateSale(
                sale_id=sale_id,
                title=title,
                organizer=organizer,
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                url=url,
                dates=dates,
                description=description,
                photo_urls=photo_urls,
                photo_count=photo_count or len(photo_urls),
                distance_miles=distance,
            )
        except Exception as e:
            logger.debug(f"Failed to parse API sale data: {e}")
            return None

    async def _parse_dom_sales(self, page, max_sales: int) -> list[EstateSale]:
        """Parse sales from the rendered DOM as a fallback."""
        sales = []

        # Try various selectors that EstateSales.net might use
        selectors_to_try = [
            "a[href*='/estate-sales/']",
            ".sale-item",
            ".sale-row",
            "[class*='sale']",
            ".listing-item",
            ".card",
        ]

        sale_elements = []
        for selector in selectors_to_try:
            elements = await page.query_selector_all(selector)
            if elements:
                logger.info(
                    f"Found {len(elements)} elements with selector '{selector}'"
                )
                sale_elements = elements
                break

        if not sale_elements:
            # Last resort: grab all links that look like sale pages
            logger.info("No sale elements found, extracting sale links from page")
            links = await page.evaluate(
                """() => {
                const links = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.href;
                    if (href.match(/\\/[A-Z]{2}\\/[^/]+\\/\\d{5}\\/\\d+/) ||
                        href.includes('/estate-sales/')) {
                        links.push({
                            href: href,
                            text: a.innerText.trim().substring(0, 500)
                        });
                    }
                });
                return links;
            }"""
            )

            for i, link in enumerate(links[:max_sales]):
                sale = EstateSale(
                    sale_id=str(i),
                    title=link.get("text", "")[:200] or f"Estate Sale {i + 1}",
                    organizer="",
                    address="",
                    city="",
                    state="",
                    zip_code="",
                    url=link.get("href", ""),
                )
                sales.append(sale)
            return sales

        for el in sale_elements[:max_sales]:
            try:
                text = (await el.inner_text()).strip()
                href = await el.get_attribute("href") or ""
                if not href:
                    link = await el.query_selector("a[href]")
                    if link:
                        href = await link.get_attribute("href") or ""

                if href and not href.startswith("http"):
                    href = urljoin(self.BASE_URL, href)

                sale = EstateSale(
                    sale_id=str(len(sales)),
                    title=text[:200],
                    organizer="",
                    address="",
                    city="",
                    state="",
                    zip_code="",
                    url=href,
                )
                sales.append(sale)
            except Exception as e:
                logger.debug(f"Failed to parse DOM sale element: {e}")

        return sales

    async def enrich_sale(self, sale: EstateSale) -> EstateSale:
        """Visit a sale's detail page to extract full description and photos."""
        if not sale.url:
            return sale

        page = await self._new_page()
        api_detail: dict = {}

        # Intercept API responses for sale detail
        async def handle_response(response):
            try:
                url = response.url
                if "/api/" in url and response.status == 200:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        if isinstance(body, dict):
                            # API wraps sale data in {"sale": {...}}
                            inner = body.get("sale", body)
                            if isinstance(inner, dict) and any(
                                k in inner
                                for k in (
                                    "plainTextDescription",
                                    "htmlDescription",
                                    "description",
                                    "pictures",
                                    "saleId",
                                )
                            ):
                                api_detail.update(inner)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await self._rate_limit()
            success = await self._safe_get(page, sale.url)
            if not success:
                return sale

            # Wait for API responses to arrive (Angular app makes XHR calls after DOM load)
            for _ in range(10):
                if api_detail:
                    break
                await asyncio.sleep(0.5)
            else:
                # Give DOM fallback a moment to settle
                await asyncio.sleep(1)

            # Use API data if intercepted
            if api_detail:
                desc = (
                    api_detail.get("plainTextDescription")
                    or api_detail.get("htmlDescription")
                    or api_detail.get("description")
                    or api_detail.get("details")
                    or ""
                )
                if desc:
                    desc = re.sub(r"<[^>]+>", " ", desc)
                    sale.description = re.sub(r"\s+", " ", desc).strip()

                if "pictures" in api_detail:
                    for pic in api_detail["pictures"]:
                        if isinstance(pic, str):
                            sale.photo_urls.append(pic)
                        elif isinstance(pic, dict):
                            url = pic.get("url", pic.get("imageUrl", ""))
                            if url:
                                sale.photo_urls.append(url)
                    sale.photo_count = len(sale.photo_urls)
            else:
                # DOM fallback for description
                desc_text = await page.evaluate(
                    """() => {
                    // Try Schema.org structured data first
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    for (const s of scripts) {
                        try {
                            const data = JSON.parse(s.textContent);
                            if (data.description) return data.description;
                        } catch(e) {}
                    }
                    // Try meta description
                    const meta = document.querySelector('meta[name="description"]');
                    if (meta) return meta.content;
                    // Try body text
                    const body = document.body.innerText;
                    return body.substring(0, 5000);
                }"""
                )
                if desc_text:
                    sale.description = desc_text[:5000]

                # DOM fallback for photos
                photo_urls = await page.evaluate(
                    """() => {
                    const urls = [];
                    document.querySelectorAll('img[src*="picturescdn"], img[src*="estate"]').forEach(img => {
                        const src = img.src || img.dataset.src || '';
                        if (src && !src.includes('logo') && !src.includes('icon')) {
                            urls.push(src);
                        }
                    });
                    return urls;
                }"""
                )
                if photo_urls:
                    sale.photo_urls = list(set(sale.photo_urls + photo_urls))
                    sale.photo_count = len(sale.photo_urls)

        finally:
            await page.close()

        return sale
