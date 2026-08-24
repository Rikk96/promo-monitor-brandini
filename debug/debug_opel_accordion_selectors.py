from playwright.sync_api import sync_playwright

URL = "https://www.opel.it/offerte/privati/corsa-finanziamento.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 1600})

    page.goto(URL, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(3000)

    print("TEXT LOCATORS:")
    loc = page.get_by_text("Nota legale e consumi", exact=False)
    print("count:", loc.count())

    for i in range(loc.count()):
        try:
            el = loc.nth(i)
            print("\n--- TEXT MATCH", i)
            print("visible:", el.is_visible())
            print("text:", el.inner_text(timeout=3000))
            print("html:", el.evaluate("e => e.outerHTML").replace("\\n", " ")[:1500])
        except Exception as e:
            print("ERR:", e)

    print("\nBUTTONS / SUMMARY / ACCORDION CANDIDATES:")
    candidates = page.locator("button, summary, [role='button'], [aria-expanded], .accordion, [class*='accordion'], [class*='legal'], [class*='Legal']")
    print("candidates:", candidates.count())

    for i in range(min(candidates.count(), 120)):
        try:
            el = candidates.nth(i)
            txt = (el.inner_text(timeout=1000) or "").strip().replace("\\n", " ")
            html = el.evaluate("e => e.outerHTML").replace("\\n", " ")
            if "Nota legale" in txt or "legale" in txt.lower() or "consumi" in txt.lower() or "legal" in html.lower():
                print("\n--- CANDIDATE", i)
                print("visible:", el.is_visible())
                print("text:", txt[:500])
                print("html:", html[:2500])
        except Exception:
            pass

    browser.close()
