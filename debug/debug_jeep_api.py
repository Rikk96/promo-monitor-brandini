from playwright.sync_api import sync_playwright

URL = "https://www.jeep-official.it/offerte-jeep-prezzi"

KEYWORDS = [
    "offer",
    "offert",
    "promo",
    "promoz",
    "campaign",
    "price",
    "prezz",
    "finance",
    "rate",
    "taeg",
    "tan",
    "json",
    "api",
    "graphql",
    "jeep"
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()

    found = []

    def handle_response(response):
        url = response.url
        low = url.lower()

        if any(k in low for k in KEYWORDS):
            found.append(url)

    page.on("response", handle_response)

    page.goto(URL, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(12000)

    print("REQUEST TROVATE:", len(set(found)))

    for url in sorted(set(found)):
        print(url)

    browser.close()
