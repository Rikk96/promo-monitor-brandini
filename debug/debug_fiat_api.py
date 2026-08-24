from playwright.sync_api import sync_playwright

URL = "https://www.fiat.it/offerte-privati"

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox"]
    )

    page = browser.new_page()

    requests_found = []

    def handle_response(response):
        url = response.url.lower()

        if any(x in url for x in [
            "json",
            "offer",
            "promo",
            "campaign",
            "graphql",
            "api"
        ]):
            requests_found.append(url)

    page.on("response", handle_response)

    page.goto(URL, wait_until="networkidle", timeout=60000)

    page.wait_for_timeout(10000)

    print("FOUND:")
    for r in sorted(set(requests_found)):
        print(r)

    browser.close()
