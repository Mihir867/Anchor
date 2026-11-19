"""Build-time smoke test: fail the image build if Playwright's chromium can't start
(missing system libraries show up here instead of in a user's job)."""
import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page()
        await page.set_content("<h1>ok</h1>")
        await page.screenshot()
        await browser.close()
    print("chromium launch OK")


asyncio.run(main())
