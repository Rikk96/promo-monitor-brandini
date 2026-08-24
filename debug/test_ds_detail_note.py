from playwright.sync_api import sync_playwright

URL="https://www.dsautomobiles.it/acquisto-noleggio/offerte-privati/ds3-acquisto.html"

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
    page=browser.new_page(viewport={"width":1366,"height":2400})

    page.goto(URL,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(5000)

    print("accordion text count:", page.get_by_text("Nota legale e consumi", exact=False).count())

    try:
        acc = page.get_by_text("Nota legale e consumi", exact=False).first
        acc.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(1000)
        acc.click(timeout=10000, force=True)
        page.wait_for_timeout(2500)
    except Exception as e:
        print("click text failed:", e)

    body=page.locator("body").inner_text(timeout=30000)

    for k in ["DETTAGLIO PROMOZIONE","Messaggio Pubblicitario","Importo Totale","Consumo","Offerta valida"]:
        print(k, "=>", body.lower().find(k.lower()))

    idx=body.lower().find("dettaglio promozione")
    if idx!=-1:
        print("\n=== NOTA ===\n")
        print(body[idx:idx+4000])
    else:
        print("\nNON TROVATA, zona Nota legale:\n")
        j=body.lower().find("nota legale e consumi")
        print(body[max(0,j-500):j+2500])

    browser.close()
