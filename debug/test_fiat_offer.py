from playwright.sync_api import sync_playwright

URL = "https://www.fiat.it/offerte-privati/grande-panda-hybrid"

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox"]
    )

    page = browser.new_page(
        viewport={"width": 1366, "height": 1200}
    )

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(5000)

    text = page.locator("body").inner_text(timeout=30000)

    print("TITLE:", page.title())
    print("URL:", page.url)
    print("TEXT LENGTH:", len(text))

    print("\n--- PRIME 3000 LETTERE ---\n")
    print(text[:3000])

    print("\n--- RICERCA KEYWORDS ---\n")

    keywords = [
        "TAN",
        "TAEG",
        "rata",
        "Offerta valida",
        "validità",
        "Messaggio pubblicitario",
        "Salvo approvazione",
        "Importo totale",
        "Prezzo"
    ]

    for kw in keywords:
        idx = text.lower().find(kw.lower())
        print(kw, "=>", idx)

        if idx != -1:
            start = max(0, idx - 300)
            end = min(len(text), idx + 800)
            print(text[start:end])
            print("\n---\n")

    browser.close()
