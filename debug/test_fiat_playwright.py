from playwright.sync_api import sync_playwright

URL = "https://www.fiat.it/offerte-privati"

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox"]
    )

    page = browser.new_page(
        viewport={"width": 1366, "height": 900}
    )

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    links = page.locator("a").evaluate_all("""
        els => els.map(a => ({
            text: (a.innerText || '').trim().replace(/\\s+/g, ' '),
            href: a.href
        }))
    """)

    filtered = []
    seen = set()

    for item in links:
        text = item["text"]
        href = item["href"]

        check = (text + " " + href).lower()

        if (
            "scopri" in check
            or "offerta" in check
            or "offerte" in check
            or "configura" in check
            or "acquista" in check
            or "promozione" in check
        ):
            if href and href not in seen:
                seen.add(href)
                filtered.append((text, href))

    print("LINK TROVATI:", len(filtered))

    for i, (text, href) in enumerate(filtered, start=1):
        print(f"{i}. {text}")
        print(f"   {href}")

    browser.close()
