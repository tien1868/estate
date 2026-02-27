from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..models.opportunity import ArbitrageOpportunity


class TerminalOutput:
    """Rich terminal output for arbitrage opportunities."""

    def __init__(self):
        self.console = Console()

    def display_opportunities(self, opportunities: list[ArbitrageOpportunity]):
        sorted_opps = sorted(
            opportunities,
            key=lambda o: o.ebay_median_sold,
            reverse=True,
        )

        self.console.print()
        self.console.print(
            Panel(
                f"[bold white]Estate Sale Arbitrage Opportunities[/bold white]\n"
                f"[dim]{len(sorted_opps)} matches found[/dim]",
                border_style="green",
            )
        )

        if not sorted_opps:
            self.console.print(
                "\n[yellow]No arbitrage opportunities found matching your criteria.[/yellow]\n"
                "[dim]Try expanding your search radius or adding more brands.[/dim]\n"
            )
            return

        for i, opp in enumerate(sorted_opps, 1):
            self._display_single(opp, i)

    def _display_single(self, opp: ArbitrageOpportunity, index: int):
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Field", style="bold cyan", width=22)
        table.add_column("Value")

        table.add_row("Sale", opp.estate_sale_title[:80])
        table.add_row("Location", opp.estate_sale_location)
        if opp.estate_sale_dates:
            table.add_row("Dates", ", ".join(opp.estate_sale_dates))

        # Brand + detection source
        source_tag = {
            "vision": "[magenta](AI Vision)[/magenta]",
            "text": "[cyan](Text Match)[/cyan]",
            "both": "[green](Text + Vision)[/green]",
        }.get(opp.detection_source, "")
        table.add_row(
            "Brand Match",
            f"[bold yellow]{opp.matched_brand}[/bold yellow] {source_tag}",
        )

        if opp.item_type:
            table.add_row("Item Type", opp.item_type)

        desc = opp.matched_description[:150]
        if len(opp.matched_description) > 150:
            desc += "..."
        table.add_row("Description", desc)

        if opp.vision_reasoning:
            reasoning = opp.vision_reasoning[:200]
            if len(opp.vision_reasoning) > 200:
                reasoning += "..."
            table.add_row("AI Insight", f"[dim]{reasoning}[/dim]")

        if opp.estate_price_estimate:
            table.add_row("Estate Price", f"${opp.estate_price_estimate:.2f}")
        else:
            table.add_row("Estate Price", "[dim]Not listed (check at sale)[/dim]")

        table.add_row(
            "eBay Median Sold",
            f"[bold green]${opp.ebay_median_sold:.2f}[/bold green]",
        )
        table.add_row("eBay Avg Sold", f"${opp.ebay_average_sold:.2f}")
        table.add_row(
            "eBay Range",
            f"${opp.ebay_price_range[0]:.2f} - ${opp.ebay_price_range[1]:.2f}",
        )
        table.add_row("Sample Size", f"{opp.ebay_sample_count} sold listings")

        if opp.profit_multiplier is not None:
            color = "green" if opp.profit_multiplier >= 2 else "yellow"
            table.add_row(
                "Profit Multiplier",
                f"[bold {color}]{opp.profit_multiplier:.1f}x[/bold {color}]",
            )
        if opp.estimated_roi_pct is not None:
            table.add_row("Est. ROI", f"{opp.estimated_roi_pct:.0f}%")

        table.add_row("Link", f"[link={opp.estate_sale_url}]{opp.estate_sale_url}[/link]")

        border_color = "green" if (opp.profit_multiplier or 0) >= 2 else "yellow"
        self.console.print(
            Panel(
                table,
                title=f"[bold]#{index}[/bold]",
                border_style=border_color,
            )
        )
        self.console.print()

    def display_summary(
        self,
        total_sales: int,
        matched_sales: int,
        total_opportunities: int,
        vision_finds: int,
    ):
        """Display a summary of the scan."""
        self.console.print()
        summary = Table(show_header=False, box=None, padding=(0, 2))
        summary.add_column("Metric", style="bold")
        summary.add_column("Value", style="bold green")
        summary.add_row("Estate sales scanned", str(total_sales))
        summary.add_row("Sales with brand matches", str(matched_sales))
        summary.add_row("Arbitrage opportunities", str(total_opportunities))
        summary.add_row("AI vision discoveries", str(vision_finds))
        self.console.print(Panel(summary, title="[bold]Scan Summary[/bold]"))
        self.console.print()
