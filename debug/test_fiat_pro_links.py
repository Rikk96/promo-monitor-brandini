from playwright.sync_api import sync_playwright

URL="https://www.fiat.it/professional/offerte"

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
    page=browser.new_page(viewport={"width":1366,"height":1800})

    page.goto(URL,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(5000)

    links=page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/professional/offerte/')
                && !h.endsWith('/offerte')
                && !h.endsWith('/offerte#')
            )
        )]
    """)

    print("LINK:",len(links))

    for l in links:
        print(l)

    browser.close()
