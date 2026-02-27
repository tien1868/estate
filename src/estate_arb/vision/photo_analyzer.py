import asyncio
import base64
import json
import logging
from io import BytesIO

import aiohttp
import boto3

logger = logging.getLogger(__name__)

VISION_PROMPT = """You are an expert vintage clothing and collectibles appraiser working for an eBay reseller.
Analyze these estate sale photos carefully. Your job is to identify items that have significant resale value on eBay.

Look for:

**CLOTHING & TEXTILES:**
- Brand labels/tags (even partially visible, inside collars, on care labels, woven into fabric)
- Vintage denim: selvedge/redline (look at outseam), chain stitch hems, specific vintage washes, old Levi's red tabs, Lee riders, Wrangler Blue Bell
- Rare fabrics: qiviut/musk ox, vicuna, cashmere (look for label details), Harris tweed, Irish linen, Loro Piana, mohair
- Designer construction: specific stitching patterns, branded hardware (zippers, buttons), unique linings
- Premium outdoor brands: Patagonia (look for logo patches), The North Face (TNF logo), Mountain Hardwear
- Designer/luxury: Ralph Lauren (polo player logo), Brooks Brothers (golden fleece), Claude Montana, Nili Lotan
- Vintage military: M-65 field jackets, M-51 parkas, military insignia, olive drab pieces with contract stamps
- Vintage leather: motorcycle jackets, bomber jackets, leather quality indicators

**COLLECTIBLES & OTHER:**
- Magic: The Gathering cards (look for card frames, mana symbols, even stacks of cards)
- Vintage band/concert t-shirts (tour dates on back = more valuable)
- Vintage NASCAR merchandise (especially 1990s-2000s era)
- Premium cookware: Mauviel copper, Le Creuset, All-Clad, Staub
- Japanese brands: Sou Sou, Kapital, Visvim, Engineered Garments

**HIDDEN VALUE INDICATORS:**
- "Made in USA", "Made in Japan", "Made in Italy", "Made in England" labels
- Union-made tags (ILGWU, UNITE, ACWA) = vintage indicator
- Hand-stitching, hand-knit items, artisan construction
- Quality hardware (YKK zippers on vintage = good, Talon/Crown zippers = very old/valuable)
- Unusual/rare items that an estate sale organizer likely wouldn't know the value of

For each item you identify, respond with a JSON array. Each entry should have:
- "brand": brand name or "Unknown" if brand not visible but item is valuable
- "item_type": what the item is (e.g., "vintage selvedge denim jacket", "qiviut scarf")
- "ebay_query": short eBay search query to find comparable sold listings, 2-5 words max (e.g., "Patagonia fleece jacket", "Le Creuset dutch oven", "vintage Levi's 501 jeans")
- "estimated_value_low": low end of eBay resale value estimate in dollars
- "estimated_value_high": high end of eBay resale value estimate in dollars
- "confidence": 0.0-1.0 how confident you are in the identification
- "reasoning": brief explanation of why this is valuable and what you see

If you see NO items of resale value, return an empty JSON array: []

Respond ONLY with valid JSON. No markdown, no explanation outside the JSON."""


class PhotoAnalyzer:
    """Analyze estate sale photos using Claude Sonnet via AWS Bedrock."""

    def __init__(
        self,
        region: str = "us-east-1",
        model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
        max_photos_per_batch: int = 10,
    ):
        self.region = region
        self.model_id = model_id
        self.max_photos_per_batch = max_photos_per_batch
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def analyze_sale_photos(
        self, photo_urls: list[str], max_photos: int = 30
    ) -> list[dict]:
        """Download and analyze estate sale photos in batches.

        Returns a list of identified items with value estimates.
        """
        urls_to_process = photo_urls[:max_photos]
        if not urls_to_process:
            return []

        # Download all photos concurrently
        logger.info(f"Downloading {len(urls_to_process)} photos...")
        images = await self._download_photos(urls_to_process)
        if not images:
            logger.warning("No photos could be downloaded")
            return []

        logger.info(f"Downloaded {len(images)} photos, analyzing with Claude Vision...")

        # Process in batches to stay within token limits
        all_items = []
        for i in range(0, len(images), self.max_photos_per_batch):
            batch = images[i : i + self.max_photos_per_batch]
            batch_items = await self._analyze_batch(batch)
            all_items.extend(batch_items)

        # Deduplicate by brand + item_type
        seen = set()
        unique_items = []
        for item in all_items:
            key = (item.get("brand", ""), item.get("item_type", ""))
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        return unique_items

    async def _download_photos(
        self, urls: list[str]
    ) -> list[tuple[bytes, str]]:
        """Download photos concurrently. Returns list of (image_bytes, media_type)."""
        async with aiohttp.ClientSession() as session:
            tasks = [self._download_one(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        images = []
        for result in results:
            if isinstance(result, tuple):
                images.append(result)
            elif isinstance(result, Exception):
                logger.debug(f"Photo download failed: {result}")
        return images

    async def _download_one(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[bytes, str]:
        """Download a single photo and return (bytes, media_type)."""
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            content_type = resp.content_type or "image/jpeg"
            # Map to Bedrock-supported media types
            media_type = self._normalize_media_type(content_type)
            data = await resp.read()
            return (data, media_type)

    @staticmethod
    def _normalize_media_type(content_type: str) -> str:
        """Normalize content type to Bedrock-supported image types."""
        ct = content_type.lower()
        if "png" in ct:
            return "image/png"
        if "gif" in ct:
            return "image/gif"
        if "webp" in ct:
            return "image/webp"
        return "image/jpeg"

    async def _analyze_batch(
        self, images: list[tuple[bytes, str]]
    ) -> list[dict]:
        """Send a batch of images to Claude via Bedrock and parse results."""
        # Build the content array with images + text prompt
        content = []
        for img_bytes, media_type in images:
            b64_data = base64.b64encode(img_bytes).decode("utf-8")
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_data,
                    },
                }
            )

        content.append({"type": "text", "text": VISION_PROMPT})

        request_body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2,
            }
        )

        try:
            # Run the synchronous boto3 call in a thread to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.invoke_model(
                    modelId=self.model_id,
                    body=request_body,
                    contentType="application/json",
                    accept="application/json",
                ),
            )

            response_body = json.loads(response["body"].read())
            stop_reason = response_body.get("stop_reason", "unknown")
            content_blocks = response_body.get("content", [])

            if not content_blocks:
                logger.warning(f"Empty content in vision response (stop_reason={stop_reason})")
                return []

            # Find the text block in the response
            text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text = block.get("text", "").strip()
                    break

            if not text:
                logger.warning(f"No text in vision response (stop_reason={stop_reason})")
                return []

            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            items = json.loads(text)
            if isinstance(items, list):
                return items
            logger.warning(f"Unexpected vision response format: {type(items)}")
            return []

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse vision response as JSON: {e}")
            logger.debug(f"Raw response text: {text[:300] if text else 'EMPTY'}")
            return []
        except Exception as e:
            logger.error(f"Bedrock vision API call failed: {e}")
            return []
