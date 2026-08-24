from playwright.sync_api import sync_playwright

URL = "https://www.fiat.it/offerte-privati"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 1600})

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)

    # scroll basso per far caricare tutto
    for i in range(6):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1500)

    links = page.locator("a").evaluate_all("""
        els => els.map(a => ({
            text: (a.innerText || '').trim().replace(/\\s+/g, ' '),
            href: a.href
        }))
    """)

    seen = set()
    offers = []

    for item in links:
        href = item.get("href") or ""
        text = item.get("text") or ""

        if "/offerte-privati/" in href and href not in seen:
            seen.add(href)
            offers.append((text, href))

    print("OFFERTE LINK TROVATE:", len(offers))

    for i, (text, href) in enumerate(offers, start=1):
        print(i, "|", text, "|", href)

    browser.close()
