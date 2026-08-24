from playwright.sync_api import sync_playwright

URL = "https://www.opel.it/offerte/privati/corsa-finanziamento.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 1800})

    page.goto(URL, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(5000)

    headers = page.locator(".q-expander-header-elem")
    print("headers:", headers.count())

    for i in range(headers.count()):
        print(i, headers.nth(i).inner_text(timeout=3000))

    # Il primo/secondo header può cambiare: clicchiamo quello che contiene Nota legale e consumi
    header = page.locator(".q-expander-header-elem").filter(has_text="Nota legale e consumi").first
    print("visible:", header.is_visible())

    # clicca il parent cliccabile dell'accordion
    header.evaluate("""
        el => {
            let p = el;
            for (let i = 0; i < 8; i++) {
                if (!p) break;
                const cls = String(p.className || '').toLowerCase();
                const aria = p.getAttribute('aria-expanded');
                const role = p.getAttribute('role');

                if (
                    role === 'button' ||
                    aria !== null ||
                    cls.includes('q-expander-header') ||
                    cls.includes('expander-header') ||
                    cls.includes('q-expander')
                ) {
                    p.click();
                    return;
                }
                p = p.parentElement;
            }
            el.click();
        }
    """)

    page.wait_for_timeout(4000)

    body = page.locator("body").inner_text(timeout=30000)

    for key in ["DETTAGLIO PROMOZIONE", "Importo Totale", "Messaggio Pubblicitario", "Offerta valida"]:
        print(key, "=>", body.lower().find(key.lower()))

    start = body.lower().find("dettaglio promozione")

    if start != -1:
        sub = body[start:]
        stops = [
            "Configura",
            "Contatta il Concessionario",
            "Pronta consegna",
            "Vetture",
            "Gamma elettrica",
            "CONTINUA SENZA ACCETTARE",
            "LA TUA PRIVACY",
        ]

        end = len(sub)
        for s in stops:
            idx = sub.find(s)
            if idx != -1:
                end = min(end, idx)

        print("\n=== NOTA LEGALE PROMO ===\n")
        print(sub[:end].strip())
    else:
        print("\nNON TROVATA. ZONA ACCORDION:\n")
        idx = body.lower().find("nota legale e consumi")
        print(body[max(0, idx-1000):idx+3000])

    browser.close()
