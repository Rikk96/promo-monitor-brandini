from playwright.sync_api import sync_playwright

URL = "https://www.fiat.it/offerte-privati"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 1600})

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)

    print("TEXT contains vedi:", "vedi" in page.locator("body").inner_text().lower())
    print("BODY TEXT SAMPLE:")
    body = page.locator("body").inner_text()
    for line in body.splitlines():
        if "vedi" in line.lower() or "promoz" in line.lower() or "mostra" in line.lower():
            print(line)

    print("\nBUTTONS:")
    buttons = page.locator("button").evaluate_all("""
        els => els.map(b => ({
            text: (b.innerText || '').trim().replace(/\\s+/g, ' '),
            aria: b.getAttribute('aria-label'),
            cls: b.className,
            id: b.id
        }))
    """)

    for i, b in enumerate(buttons):
        print(i, b)

    print("\nLINK COUNT BEFORE:", page.locator("a").count())

    browser.close()
