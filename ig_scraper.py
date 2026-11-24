# ig_scraper.py

from playwright.async_api import async_playwright

async def scrape_ig_video(url: str) -> tuple[str, str] | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            print(f"Membuka: {url}")
            await page.goto(url, timeout=20000)

            # Locate video element
            await page.wait_for_selector("video", timeout=15000)
            video = await page.query_selector("video")
            video_url = await video.get_attribute("src") if video else None

            # Extract caption
            caption = ""
            possible_selectors = [
                'ul li div > div > div > span',  # common fallback selector
                'div._aacl._aaco._aacu._aacx._aad7 > span',
                'div._a9zs > span',
            ]
            for selector in possible_selectors:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        txt = await el.inner_text()
                        if txt:
                            caption = txt.strip()
                            print(f"Caption ditemukan: {caption[:100]}...")
                            break
                except Exception as e:
                    print(f"Gagal selector: {selector} -> {e}")

            return video_url, caption
        except Exception as e:
            print("Scrape error:", e)
            return None
        finally:
            await browser.close()
