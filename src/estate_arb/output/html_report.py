import html
import logging
from datetime import datetime
from pathlib import Path

from ..models.opportunity import ArbitrageOpportunity

logger = logging.getLogger(__name__)

# Keyword-based category classification
_CATEGORIES = {
    "Electronics": [
        "tv", "television", "monitor", "console", "xbox", "playstation",
        "nintendo", "switch", "n64", "camera", "lens", "printer", "computer",
        "laptop", "speaker", "stereo", "receiver", "amplifier", "cd player",
        "dvd", "blu-ray", "projector", "radio", "turntable", "record player",
        "phone", "tablet", "gaming", "headphone", "keyboard",
    ],
    "Clothing & Fashion": [
        "jacket", "coat", "blazer", "shirt", "sweater", "vest", "dress",
        "pants", "jeans", "denim", "boots", "shoes", "hat", "scarf",
        "handbag", "purse", "wallet", "leather", "fur", "mink", "cardigan",
        "jumpsuit", "coverall", "fleece",
    ],
    "Jewelry & Watches": [
        "watch", "ring", "necklace", "bracelet", "earring", "brooch",
        "pendant", "sterling", "silver", "gold", "diamond", "tiffany",
        "jewelry", "jewellery", "chain", "pin", "tie clip",
    ],
    "Collectibles": [
        "pokemon", "magic", "mtg", "card", "comic", "star wars", "nascar",
        "bobblehead", "figurine", "doll", "barbie", "animation cel",
        "memorabilia", "autograph", "signed", "coin", "stamp", "toy",
        "die-cast", "model", "hot wheels", "lego",
    ],
    "Art & Decor": [
        "painting", "print", "art", "sculpture", "poster", "lithograph",
        "lamp", "tiffany style", "vase", "stained glass", "frame",
        "tapestry", "rug", "screen", "mirror",
    ],
    "Tools & Equipment": [
        "drill", "saw", "welder", "welding", "compressor", "wrench",
        "tool", "lathe", "grinder", "sander", "router", "winch",
        "generator", "mower", "chainsaw", "impact", "cordless",
    ],
    "Home & Kitchen": [
        "cookware", "dutch oven", "le creuset", "pyrex", "corning",
        "fiesta", "dish", "bowl", "pot", "pan", "mixer", "blender",
        "vacuum", "appliance", "washer", "dryer", "refrigerator",
        "freezer", "furniture", "table", "chair", "cabinet", "desk",
    ],
    "Sports & Outdoors": [
        "kayak", "fishing", "rod", "reel", "bike", "bicycle", "golf",
        "ski", "snowboard", "tent", "camp", "grill", "saddle", "wader",
        "canteen", "hiking", "boat", "canoe",
    ],
    "Vintage & Antiques": [
        "typewriter", "clock", "antique", "phonograph", "washboard",
        "crock", "stoneware", "brass", "copper", "pewter", "tin",
        "advertising", "sewing machine", "register", "orrery",
    ],
}


def _categorize(opp: ArbitrageOpportunity) -> str:
    """Assign a category based on item type, brand, and description keywords."""
    text = " ".join([
        opp.item_type or "",
        opp.matched_brand or "",
        opp.matched_description or "",
        opp.vision_reasoning or "",
    ]).lower()

    for category, keywords in _CATEGORIES.items():
        for kw in keywords:
            if kw in text:
                return category
    return "Other"


def generate_html_report(
    opportunities: list[ArbitrageOpportunity],
    total_sales: int = 0,
    matched_sales: int = 0,
    vision_finds: int = 0,
    output_dir: str = "public",
) -> str:
    """Generate a self-contained HTML report of arbitrage opportunities."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"

    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    rows = _build_rows(opportunities)

    # Collect category counts for filter buttons
    cat_counts: dict[str, int] = {}
    for opp in opportunities:
        cat = _categorize(opp)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    # Sort by count descending
    sorted_cats = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
    filter_buttons = ''.join(
        f'<button class="filter-btn" data-cat="{cat}" onclick="filterCat(this)">'
        f'{cat} <span class="count">{count}</span></button>'
        for cat, count in sorted_cats
    )

    content = _TEMPLATE.replace("{{GENERATED}}", now)
    content = content.replace("{{TOTAL_SALES}}", str(total_sales))
    content = content.replace("{{MATCHED_SALES}}", str(matched_sales))
    content = content.replace("{{OPPORTUNITIES}}", str(len(opportunities)))
    content = content.replace("{{VISION_FINDS}}", str(vision_finds))
    content = content.replace("{{FILTER_BUTTONS}}", filter_buttons)
    content = content.replace("{{ROWS}}", rows)

    path.write_text(content, encoding="utf-8")
    logger.info(f"HTML report written to {path}")
    return str(path)


def _esc(text: str) -> str:
    return html.escape(str(text)) if text else ""


def _source_badge(source: str) -> str:
    colors = {
        "vision": ("#d946ef", "AI Vision"),
        "text": ("#06b6d4", "Text Match"),
        "both": ("#22c55e", "Text + Vision"),
    }
    color, label = colors.get(source, ("#94a3b8", source))
    return f'<span class="badge" style="background:{color}">{label}</span>'


_CAT_COLORS = {
    "Electronics": "#3b82f6",
    "Clothing & Fashion": "#ec4899",
    "Jewelry & Watches": "#f59e0b",
    "Collectibles": "#8b5cf6",
    "Art & Decor": "#f97316",
    "Tools & Equipment": "#64748b",
    "Home & Kitchen": "#14b8a6",
    "Sports & Outdoors": "#22c55e",
    "Vintage & Antiques": "#a78bfa",
    "Other": "#475569",
}


def _build_rows(opportunities: list[ArbitrageOpportunity]) -> str:
    sorted_opps = sorted(
        opportunities, key=lambda o: o.ebay_median_sold or 0, reverse=True
    )
    parts = []
    for i, opp in enumerate(sorted_opps, 1):
        brand = _esc(opp.matched_brand)
        item_type = _esc(opp.item_type) or _esc(opp.matched_description)
        location = _esc(opp.estate_sale_location)
        title = _esc(opp.estate_sale_title)
        link = _esc(opp.estate_sale_url)
        source = _source_badge(opp.detection_source)
        reasoning = _esc(opp.vision_reasoning)
        median = f"${opp.ebay_median_sold:,.2f}" if opp.ebay_median_sold else "N/A"
        avg = f"${opp.ebay_average_sold:,.2f}" if opp.ebay_average_sold else "N/A"
        low, high = opp.ebay_price_range or (0, 0)
        price_range = f"${low:,.2f} - ${high:,.2f}" if high else "N/A"
        samples = opp.ebay_sample_count or 0
        estate_price = (
            f"${opp.estate_price_estimate:,.2f}"
            if opp.estate_price_estimate
            else "Not listed"
        )

        category = _categorize(opp)
        cat_color = _CAT_COLORS.get(category, "#475569")
        cat_badge = f'<span class="badge cat-badge" style="background:{cat_color}">{category}</span>'

        detail_parts = []
        if title:
            detail_parts.append(f"<strong>Sale:</strong> {title}")
        if reasoning:
            detail_parts.append(f"<strong>AI Insight:</strong> {reasoning}")
        detail_parts.append(f"<strong>eBay Avg:</strong> {avg}")
        detail_parts.append(f"<strong>eBay Range:</strong> {price_range}")
        detail_parts.append(f"<strong>Samples:</strong> {samples} sold listings")
        detail_parts.append(f"<strong>Estate Price:</strong> {estate_price}")
        detail_html = "<br>".join(detail_parts)

        parts.append(f"""
        <tr class="main-row" data-cat="{_esc(category)}" onclick="toggleDetail(this)">
            <td class="rank">{i}</td>
            <td>
                <div class="item-name">{brand}</div>
                <div class="item-type">{item_type}</div>
                {source} {cat_badge}
            </td>
            <td>{location}</td>
            <td class="price">{median}</td>
            <td class="samples">{samples}</td>
            <td><a href="{link}" target="_blank" rel="noopener">View Sale</a></td>
        </tr>
        <tr class="detail-row" data-cat="{_esc(category)}" style="display:none">
            <td colspan="6">
                <div class="detail">{detail_html}</div>
            </td>
        </tr>""")

    return "\n".join(parts)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Estate Sale Arbitrage Scanner</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:16px;max-width:1200px;margin:0 auto}
h1{font-size:1.5rem;color:#f8fafc;margin-bottom:4px}
.subtitle{color:#94a3b8;font-size:.85rem;margin-bottom:20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}
.stat{background:#1e293b;border-radius:10px;padding:16px;text-align:center}
.stat-value{font-size:1.8rem;font-weight:700;color:#22c55e}
.stat-label{font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-top:4px}
.filters{margin-bottom:16px}
.filters-label{font-size:.75rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
.filter-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.filter-btn{background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:6px 14px;border-radius:9999px;font-size:.8rem;cursor:pointer;transition:all .15s}
.filter-btn:hover{background:#334155;border-color:#475569}
.filter-btn.active{background:#3b82f6;border-color:#3b82f6;color:#fff}
.filter-btn .count{opacity:.6;font-size:.7rem;margin-left:2px}
.search-box{background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 14px;border-radius:8px;font-size:.85rem;width:100%;max-width:300px;outline:none;transition:border .15s}
.search-box:focus{border-color:#3b82f6}
.search-box::placeholder{color:#64748b}
.filter-row{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;margin-bottom:16px}
.filter-row .filter-bar{flex:1}
table{width:100%;border-collapse:collapse;background:#1e293b;border-radius:10px;overflow:hidden}
thead{background:#334155}
th{padding:12px 14px;text-align:left;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;font-weight:600}
td{padding:12px 14px;border-top:1px solid #334155;font-size:.9rem}
.main-row{cursor:pointer;transition:background .15s}
.main-row:hover{background:#334155}
.rank{color:#64748b;font-weight:700;width:40px}
.item-name{font-weight:600;color:#f8fafc}
.item-type{color:#94a3b8;font-size:.8rem;margin:2px 0 4px}
.price{font-weight:700;color:#22c55e;font-size:1.05rem;white-space:nowrap}
.samples{color:#94a3b8;text-align:center}
a{color:#38bdf8;text-decoration:none}
a:hover{text-decoration:underline}
.badge{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:.7rem;font-weight:600;color:#fff}
.cat-badge{font-size:.65rem;opacity:.9}
.detail{padding:8px 0;color:#cbd5e1;font-size:.85rem;line-height:1.7}
.detail strong{color:#f8fafc}
.detail-row td{background:#0f172a;padding:4px 14px 12px 54px}
.no-results{text-align:center;padding:40px;color:#64748b;font-size:.9rem}
.footer{text-align:center;color:#475569;font-size:.75rem;margin-top:20px;padding:10px}
@media(max-width:640px){
  .stats{grid-template-columns:repeat(2,1fr)}
  th:nth-child(5),td:nth-child(5){display:none}
  td{padding:10px 8px;font-size:.82rem}
  .detail-row td{padding-left:8px}
  .filter-row{flex-direction:column}
  .search-box{max-width:100%}
}
</style>
</head>
<body>
<h1>Estate Sale Arbitrage Scanner</h1>
<p class="subtitle">Scan generated {{GENERATED}}</p>

<div class="stats">
  <div class="stat"><div class="stat-value">{{TOTAL_SALES}}</div><div class="stat-label">Sales Scanned</div></div>
  <div class="stat"><div class="stat-value">{{MATCHED_SALES}}</div><div class="stat-label">With Matches</div></div>
  <div class="stat"><div class="stat-value" style="color:#d946ef">{{VISION_FINDS}}</div><div class="stat-label">AI Vision Finds</div></div>
  <div class="stat"><div class="stat-value">{{OPPORTUNITIES}}</div><div class="stat-label">Opportunities</div></div>
</div>

<div class="filter-row">
  <div>
    <div class="filters-label">Filter by category</div>
    <div class="filter-bar">
      <button class="filter-btn active" data-cat="all" onclick="filterCat(this)">All <span class="count">{{OPPORTUNITIES}}</span></button>
      {{FILTER_BUTTONS}}
    </div>
  </div>
  <div>
    <div class="filters-label">Search</div>
    <input type="text" class="search-box" placeholder="Search items, brands, locations..." oninput="searchFilter(this.value)">
  </div>
</div>

<table>
<thead>
<tr>
  <th>#</th>
  <th>Item</th>
  <th>Location</th>
  <th>eBay Median</th>
  <th>Samples</th>
  <th>Sale</th>
</tr>
</thead>
<tbody id="results">
{{ROWS}}
</tbody>
</table>
<div class="no-results" id="no-results" style="display:none">No items match your filters.</div>

<div class="footer">
  Estate Sale Arbitrage Scanner &mdash; AI-powered scouting with eBay price cross-referencing
</div>

<script>
let activeCat='all', searchTerm='';

function toggleDetail(row){
  const detail=row.nextElementSibling;
  detail.style.display=detail.style.display==='none'?'table-row':'none';
}

function filterCat(btn){
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  activeCat=btn.dataset.cat;
  applyFilters();
}

function searchFilter(val){
  searchTerm=val.toLowerCase();
  applyFilters();
}

function applyFilters(){
  const rows=document.querySelectorAll('.main-row');
  let visible=0;
  rows.forEach(row=>{
    const detail=row.nextElementSibling;
    const cat=row.dataset.cat;
    const text=row.innerText.toLowerCase();
    const catMatch=activeCat==='all'||cat===activeCat;
    const searchMatch=!searchTerm||text.includes(searchTerm);
    const show=catMatch&&searchMatch;
    row.style.display=show?'':'none';
    detail.style.display='none';
    if(show)visible++;
  });
  document.getElementById('no-results').style.display=visible?'none':'block';
}
</script>
</body>
</html>"""
