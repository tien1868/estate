import argparse
import asyncio
import logging
import os
import sys

# Force UTF-8 output on Windows so Rich spinners render correctly
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from .config import load_brands, load_settings, BrandConfig
from .scrapers.estatesales import EstateSalesScraper
from .scrapers.ebay import EbaySoldScraper
from .vision.photo_analyzer import PhotoAnalyzer
from .matching.brand_matcher import BrandMatcher
from .matching.price_analyzer import PriceAnalyzer
from .cache.disk_cache import DiskCache
from .models.estate_sale import SaleItem
from .models.opportunity import ArbitrageOpportunity
from .output.html_report import generate_html_report
import re as _re
import subprocess


def _simplify_query(brand: str, item_type: str) -> str:
    """Turn a verbose vision description into a short eBay search query."""
    # Drop "Unknown" brand
    brand_part = "" if not brand or brand.lower() == "unknown" else brand
    # Strip parenthetical details and slash-alternatives
    simple = _re.sub(r"\(.*?\)", "", item_type)
    simple = simple.split("/")[0]
    # Remove brand name from item_type to avoid duplication
    if brand_part:
        simple = _re.sub(_re.escape(brand_part), "", simple, flags=_re.IGNORECASE)
    # Drop noise words
    words = simple.split()
    noise = {
        "vintage", "antique", "original", "authentic", "genuine", "classic",
        "various", "unknown", "with", "and", "the", "for", "from", "set",
        "collection", "collectible", "collectibles", "style", "type",
    }
    core = [w for w in words if w.lower() not in noise]
    core = core[:3] if core else words[:2]
    suffix = " ".join(core).strip()
    query = f"{brand_part} {suffix}".strip()
    if len(query) > 50:
        query = query[:50].rsplit(" ", 1)[0]
    return query
from .output.terminal import TerminalOutput

logger = logging.getLogger(__name__)


async def run(args):
    console = Console()
    settings = load_settings(args.settings)
    brands = load_brands(args.brands)
    brands_by_name = {b.name: b for b in brands}

    zip_code = args.zip or settings.zip_code
    state = args.state or ""
    city = args.city or ""
    multiplier = args.multiplier or settings.min_profit_multiplier
    headless = settings.headless_browser and not args.visible

    matcher = BrandMatcher(brands)
    cache = DiskCache(ttl_hours=settings.cache_ttl_hours)
    output = TerminalOutput()
    vision = PhotoAnalyzer(
        region=settings.aws_region,
        model_id=settings.bedrock_model_id,
        max_photos_per_batch=10,
    )

    console.print()
    console.print(f"[bold green]Estate Sale Arbitrage Scanner[/bold green]")
    console.print(f"[dim]Searching near ZIP {zip_code} | Min profit: {multiplier}x[/dim]")
    console.print()

    # ── Phase 1: Scrape estate sales ──
    console.print("[bold]Phase 1:[/bold] Searching EstateSales.net...")
    async with EstateSalesScraper(
        delay=settings.request_delay_seconds,
        headless=headless,
        user_agent=settings.user_agent,
    ) as es_scraper:
        sales = await es_scraper.search_sales(
            zip_code=zip_code,
            state=state,
            city=city,
            max_sales=settings.max_estate_sales,
        )
        console.print(f"  Found [bold]{len(sales)}[/bold] local estate sales [dim](online auctions filtered out)[/dim]")

        if not sales:
            console.print("[yellow]No estate sales found. Try a different ZIP or wider area.[/yellow]")
            return

        # Enrich each sale with descriptions and photos
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("Loading sale details...", total=len(sales))
            for sale in sales:
                await es_scraper.enrich_sale(sale)
                progress.advance(task)

    # ── Phase 2: Text-based brand matching ──
    console.print("\n[bold]Phase 2:[/bold] Scanning descriptions for target brands...")
    matched_sales = []
    for sale in sales:
        items = matcher.match_sale(sale)
        if items:
            sale.matched_items = items
            matched_sales.append(sale)
    console.print(
        f"  [bold]{len(matched_sales)}[/bold] sales with text-based brand matches"
    )

    # ── Phase 3: AI Vision analysis ──
    vision_finds = 0
    if not args.no_vision:
        console.print("\n[bold]Phase 3:[/bold] AI Vision scanning photos for hidden gems...")

        # Analyze photos for ALL sales (not just text matches)
        # This is where we find the Qiviut sweaters and hidden gold
        sales_with_photos = [s for s in sales if s.photo_urls]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Analyzing photos with Claude Vision...",
                total=len(sales_with_photos),
            )
            for sale in sales_with_photos:
                try:
                    vision_items = await vision.analyze_sale_photos(
                        sale.photo_urls,
                        max_photos=settings.max_photos_per_sale,
                    )

                    for vi in vision_items:
                        brand = vi.get("brand", "Unknown")
                        item_type = vi.get("item_type", "")
                        ebay_query = vi.get("ebay_query", "")
                        est_low = vi.get("estimated_value_low", 0)
                        est_high = vi.get("estimated_value_high", 0)
                        confidence = vi.get("confidence", 0.5)
                        reasoning = vi.get("reasoning", "")

                        # Check if this brand was already found via text
                        existing = [
                            it for it in sale.matched_items if it.brand == brand
                        ]
                        if existing:
                            existing[0].source = "both"
                            existing[0].reasoning = reasoning
                            continue

                        # New vision-only find
                        sale_item = SaleItem(
                            brand=brand,
                            description=f"{item_type} (identified by AI vision)",
                            confidence=confidence,
                            source="vision",
                            item_type=item_type,
                            reasoning=reasoning,
                            ebay_query=ebay_query,
                        )
                        sale.matched_items.append(sale_item)
                        vision_finds += 1

                        if sale not in matched_sales:
                            matched_sales.append(sale)
                except Exception as e:
                    logger.warning(f"Vision analysis failed for '{sale.title}': {e}")

                progress.advance(task)

        console.print(
            f"  AI Vision found [bold magenta]{vision_finds}[/bold magenta] "
            f"additional items not in descriptions"
        )
    else:
        console.print("\n[dim]Phase 3: AI Vision skipped (--no-vision flag)[/dim]")

    if not matched_sales:
        console.print(
            "\n[yellow]No brand matches found in any sales. "
            "Try adding more brands to config/brands.json.[/yellow]"
        )
        return

    # ── Phase 4: eBay price cross-reference ──
    console.print("\n[bold]Phase 4:[/bold] Cross-referencing eBay sold prices...")
    opportunities: list[ArbitrageOpportunity] = []

    async with EbaySoldScraper(
        delay=settings.ebay_request_delay_seconds,
        headless=headless,
        user_agent=settings.user_agent,
    ) as ebay_scraper:
        total_items = sum(len(s.matched_items) for s in matched_sales)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Looking up eBay sold prices...", total=total_items
            )

            for sale in matched_sales:
                for item in sale.matched_items:
                    # Build eBay search query
                    brand_config = brands_by_name.get(item.brand)
                    if brand_config:
                        suffix = brand_config.ebay_search_suffix
                        min_price = brand_config.min_ebay_price
                        query = f"{item.brand} {suffix}".strip()
                    else:
                        # Vision-discovered: use ebay_query if available
                        min_price = 15
                        query = item.ebay_query or _simplify_query(
                            item.brand, item.item_type
                        )

                    # Check cache first
                    cached = cache.get(query)
                    if cached and not args.no_cache:
                        stats = cached
                    else:
                        listings = await ebay_scraper.search_sold(
                            query, max_pages=settings.max_ebay_pages
                        )
                        stats = PriceAnalyzer.analyze(listings)
                        cache.set(query, stats)

                    if stats["count"] > 0 and stats["median"] >= min_price:
                        profit_mult = None
                        if item.estimated_price and item.estimated_price > 0:
                            profit_mult = stats["median"] / item.estimated_price

                        opp = ArbitrageOpportunity(
                            estate_sale_title=sale.title,
                            estate_sale_url=sale.url,
                            estate_sale_dates=sale.dates,
                            estate_sale_location=(
                                f"{sale.city}, {sale.state} {sale.zip_code}".strip(", ")
                            ),
                            matched_brand=item.brand,
                            matched_description=item.description,
                            detection_source=item.source,
                            estate_price_estimate=item.estimated_price,
                            ebay_median_sold=stats["median"],
                            ebay_average_sold=stats["average"],
                            ebay_sample_count=stats["count"],
                            ebay_price_range=(stats["min"], stats["max"]),
                            profit_multiplier=profit_mult,
                            photo_urls=item.photo_urls,
                            item_type=item.item_type,
                            vision_reasoning=item.reasoning,
                        )

                        # Include if: no estate price known, or meets multiplier threshold
                        if profit_mult is None or profit_mult >= multiplier:
                            opportunities.append(opp)

                    progress.advance(task)

    # ── Phase 5: Output results ──
    output.display_summary(
        total_sales=len(sales),
        matched_sales=len(matched_sales),
        total_opportunities=len(opportunities),
        vision_finds=vision_finds,
    )
    output.display_opportunities(opportunities)

    # ── Phase 6: HTML report ──
    report_path = generate_html_report(
        opportunities,
        total_sales=len(sales),
        matched_sales=len(matched_sales),
        vision_finds=vision_finds,
    )
    console.print(f"\n[bold]HTML report:[/bold] {report_path}")

    if args.deploy:
        console.print("[bold]Deploying to Vercel...[/bold]")
        try:
            result = subprocess.run(["vercel", "--prod", "--yes"], cwd=".")
            if result.returncode == 0:
                console.print("[bold green]Deployed successfully![/bold green]")
            else:
                console.print("[red]Vercel deploy failed.[/red]")
        except FileNotFoundError:
            console.print("[red]Vercel CLI not found. Install with: npm install -g vercel[/red]")


def main():
    parser = argparse.ArgumentParser(
        description="Estate Sale Arbitrage Finder — find underpriced items to flip on eBay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  estate-arb --zip 07042 --state NJ --city Montclair\n"
            "  estate-arb --zip 10001 --multiplier 3.0 --visible\n"
            "  estate-arb --zip 07042 --state NJ --city Montclair --no-vision\n"
        ),
    )
    parser.add_argument("--zip", help="ZIP code to search near")
    parser.add_argument("--state", help="State abbreviation (e.g., NJ)")
    parser.add_argument("--city", help="City name (e.g., Montclair)")
    parser.add_argument(
        "--multiplier",
        type=float,
        help="Minimum profit multiplier (default: 2.0)",
    )
    parser.add_argument(
        "--brands",
        default="config/brands.json",
        help="Path to brands config file",
    )
    parser.add_argument(
        "--settings",
        default="config/settings.json",
        help="Path to settings config file",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached eBay prices",
    )
    parser.add_argument(
        "--no-vision",
        action="store_true",
        help="Skip AI vision photo analysis (faster, no API cost)",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Show browser windows (not headless)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy HTML report to Vercel after scan",
    )

    args = parser.parse_args()

    # Set up logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy loggers
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        Console().print("\n[yellow]Scan cancelled.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
