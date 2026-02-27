import asyncio
import logging
import random

from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger(__name__)


class BaseScraper:
    """Base class providing Playwright browser management, rate limiting, and retry logic."""

    def __init__(
        self,
        delay: float = 2.0,
        headless: bool = True,
        user_agent: str | None = None,
    ):
        self.delay = delay
        self.headless = headless
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        self._browser: Browser | None = None
        self._playwright = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _new_page(self) -> Page:
        context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1920, "height": 1080},
        )
        return await context.new_page()

    async def _rate_limit(self):
        jitter = random.uniform(0.5, 1.5)
        await asyncio.sleep(self.delay * jitter)

    async def _safe_get(
        self,
        page: Page,
        url: str,
        wait_selector: str | None = None,
        wait_until: str = "domcontentloaded",
        timeout: int = 15000,
        max_retries: int = 3,
    ) -> bool:
        for attempt in range(max_retries):
            try:
                await page.goto(url, wait_until=wait_until, timeout=timeout)
                if wait_selector:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                return True
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url}: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to load {url} after {max_retries} attempts")
                    return False
                await asyncio.sleep(2 ** attempt)
        return False
