from playwright.sync_api import sync_playwright

URL = "https://www.fiat.it/offerte-privati"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 1600})

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)

    print("PRIMA LINK:", page.locator("a").count())

    locators = [
        "text=VEDI PIÙ PROMOZIONI",
        "text=VEDI PIU PROMOZIONI",
        "text=/VEDI.*PROMOZIONI/i",
        "xpath=//*[contains(translate(text(),'abcdefghijklmnopqrstuvwxyzàèéìòù','ABCDEFGHIJKLMNOPQRSTUVWXYZÀÈÉÌÒÙ'),'VEDI') and contains(translate(text(),'abcdefghijklmnopqrstuvwxyzàèéìòù','ABCDEFGHIJKLMNOPQRSTUVWXYZÀÈÉÌÒÙ'),'PROMOZIONI')]"
    ]

    for sel in locators:
        try:
            l = page.locator(sel)
            print("SEL:", sel, "COUNT:", l.count())
            if l.count() > 0:
                print("TEXT:", l.first.inner_text(timeout=3000))
                l.first.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(1000)
                l.first.click(timeout=5000, force=True)
                page.wait_for_timeout(5000)
                print("CLICK OK")
                break
        except Exception as e:
            print("ERRORE SEL:", sel, e)

    print("DOPO LINK:", page.locator("a").count())

    links = page.locator("a").evaluate_all("""
        els => els.map(a => ({
            text: (a.innerText || '').trim().replace(/\\s+/g, ' '),
            href: a.href
        }))
    """)

    offers = []
    seen = set()

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
