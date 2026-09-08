# /// script
# requires-python = ">=3.14"
# dependencies = ["playwright==1.62.0"]
# ///
"""Standalone browser regression checks. All HTTP traffic is intercepted locally."""

import copy
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright  # ty: ignore[unresolved-import]

STATIC = Path(__file__).resolve().parents[1] / "src/food_deals_mvp/static"
ORIGIN = "http://food-deals.test"
TILE = '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ecdf"/></svg>'


def snapshot():
    rows = []
    for index, (latitude, longitude) in enumerate(
        [(1.43, 103.95), (1.30, 103.80), (1.30, 103.80)]
    ):
        rows.append(
            {
                "deal_id": f"deal-{index}",
                "title": f"Offer {index}",
                "latitude": latitude,
                "longitude": longitude,
                "merchant": "Example café",
                "location_label": f"Venue {index}",
                "unit": "01-01",
                "source_name": "Example channel",
                "posted_at": f"2026-08-{26 - index}T10:00:00+08:00",
                "precision": "building",
                "validity_status": ["valid", "outside_period", "unknown"][index],
                "image_url": "/media/example",
                "description": "A sample offer",
                "terms": ["While stocks last"],
                "source_caption": '<img src=x onerror="window.injected=true"> Caption',
                "telegram_url": "https://t.me/example/1",
                "information_links": [
                    "javascript:alert(1)",
                    "https://example.com/info",
                ],
                "availability": {
                    "start_date": None,
                    "end_date": None,
                    "valid_dates": None,
                    "weekdays": None,
                    "restrictions_text": ["Dine-in only"],
                },
            }
        )
    return {
        "deals": rows,
        "filters": {"as_of": "2026-08-26", "validity": "all", "max_age_days": 60},
        "generated_at": "2026-09-07T08:30:00Z",
        "source_date_range": ["2026-08-01", "2026-08-31"],
        "dataset_complete": False,
        "processing_summary": {"published_rows": 3},
        "attribution": [
            {
                "text": "© OpenStreetMap contributors",
                "url": "https://www.openstreetmap.org/copyright",
                "licence": "ODbL 1.0",
            }
        ],
    }


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        mode = {
            "api_error": False,
            "tile_error": False,
            "no_map": False,
            "unmapped": False,
        }
        api_requests = []

        def route_request(route):
            url = urlsplit(route.request.url)
            if url.hostname == "tile.openstreetmap.org":
                if mode["tile_error"]:
                    route.abort()
                else:
                    route.fulfill(content_type="image/svg+xml", body=TILE)
            elif url.hostname != "food-deals.test":
                raise AssertionError(
                    f"Unexpected external request: {route.request.url}"
                )
            elif url.path == "/api/deals":
                api_requests.append(url.query)
                if mode["api_error"]:
                    route.fulfill(status=503, json={"detail": "Unavailable"})
                    return
                data = snapshot()
                params = parse_qs(url.query)
                data["filters"]["as_of"] = params.get("as_of", ["2026-08-26"])[0]
                data["filters"]["validity"] = params.get("validity", ["all"])[0]
                if data["filters"]["validity"] == "valid":
                    data["deals"] = data["deals"][:1]
                if data["filters"]["as_of"] == "2026-01-01" or mode["unmapped"]:
                    data["deals"] = []
                if mode["unmapped"]:
                    data["processing_summary"]["published_rows"] = 0
                route.fulfill(json=data)
            elif url.path.startswith("/media/"):
                route.fulfill(status=404)
            else:
                relative = (
                    "index.html"
                    if url.path == "/"
                    else url.path.removeprefix("/static/")
                )
                path = (STATIC / relative).resolve()
                assert path.is_relative_to(STATIC) and path.is_file(), path
                if path.name == "leaflet.js":
                    if mode["no_map"]:
                        route.abort()
                        return
                    # Capture the real Leaflet instance in this test only.
                    body = (
                        path.read_text()
                        + "\nconst originalMap = L.map; L.map = (...args) => (window.testMap = originalMap(...args));"
                    )
                    route.fulfill(content_type="text/javascript", body=body)
                else:
                    route.fulfill(path=path)

        context.route("**/*", route_request)

        def count(expected):
            page.wait_for_function(
                "n => document.querySelectorAll('.deal-card').length === n && document.querySelector('#deal-list').getAttribute('aria-busy') === 'false'",
                arg=expected,
            )

        def date(value):
            page.locator("#as-of").fill(value)
            page.locator("#as-of").dispatch_event("change")

        def selected():
            return page.locator(".deal-card.selected").get_attribute("data-deal-id")

        def map_view(lat, lng, zoom):
            page.evaluate(
                "([lat, lng, zoom]) => testMap.setView([lat, lng], zoom, {animate: false})",
                [lat, lng, zoom],
            )

        page.goto(ORIGIN)
        count(3)
        assert page.locator("#as-of").input_value() == "2026-08-26"
        assert not page.locator("#valid-only").is_checked()
        assert "Posted within 60 days" in page.locator("#dataset-meta").inner_text()
        assert page.locator(".pin-number").all_text_contents() == ["1", "2", "3"]
        assert page.locator(".number").all_text_contents() == ["1", "2", "3"]
        assert page.locator("#sample-note").is_visible()
        assert page.locator(".leaflet-control-attribution").is_visible()
        assert page.locator(".validity.unknown").inner_text() == "Validity unknown"
        assert "End date not stated" in page.locator(".deal-card").first.inner_text()
        print("PASS initial filters, numbering, metadata, attribution")

        request_count = len(api_requests)
        for selector, key in [
            ("#map", "ArrowRight"),
            (".leaflet-control-zoom-in", "Enter"),
        ]:
            page.evaluate(
                "() => { window.motionDone = false; testMap.once('moveend', () => { window.motionDone = true; }); }"
            )
            page.locator(selector).focus()
            page.locator(selector).press(key)
            page.wait_for_function("window.motionDone")
        assert len(api_requests) == request_count
        page.locator("#show-all").click()
        count(3)

        # Keyboard list selection opens the same numbered popup without refitting.
        original_bounds = page.evaluate("testMap.getBounds().toBBoxString()")
        button = page.locator(".card-select").nth(1)
        button.focus()
        button.press("Enter")
        assert selected() == "deal-1"
        assert (
            page.locator(".leaflet-popup-content strong").inner_text() == "2. Offer 1"
        )
        assert page.evaluate("testMap.getBounds().toBBoxString()") == original_bounds
        assert (
            page.locator(".deal-card.selected details").get_attribute("open")
            is not None
        )
        assert (
            page.locator(".deal-card.selected .caption").inner_text().startswith("<img")
        )
        assert page.locator(".caption img").count() == 0
        assert page.locator('a[href^="javascript:"]').count() == 0
        assert (
            page.locator(".source-links a").first.get_attribute("rel")
            == "noopener noreferrer"
        )
        page.wait_for_function(
            "document.querySelector('.deal-card').textContent.includes('Source image unavailable')"
        )
        print("PASS keyboard selection, no auto-pan, safe text/links, missing images")

        request_count = len(api_requests)
        map_view(1.30, 103.80, 15)
        count(2)
        assert selected() == "deal-1"
        assert page.locator(".deal-card.selected .number").inner_text() == "1"
        assert page.locator(".pin-number").all_text_contents() == ["1", "2"]
        assert len(api_requests) == request_count
        expect(page.locator(".leaflet-popup-close-button")).to_have_count(1)
        page.locator(".leaflet-popup-close-button").click()
        page.locator(".deal-pin.selected").click()
        assert page.locator(".popup-choices button").all_text_contents() == [
            "1. Offer 1",
            "2. Offer 2",
        ]
        page.locator(".popup-choices button").nth(1).press("Enter")
        assert selected() == "deal-2"
        assert page.locator(".deal-card.selected .card-select").evaluate(
            "el => el === document.activeElement"
        )
        map_view(1.43, 103.95, 15)
        count(1)
        assert page.locator(".deal-card.selected").count() == 0
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        map_view(1.2, 103.6, 15)
        count(0)
        assert "No deals in this area" in page.locator("#status").inner_text()
        page.locator("#show-all").click()
        count(3)
        print(
            "PASS local viewport filtering, stable selection, overlap chooser, empty area"
        )

        page.locator(".card-select").nth(1).click()
        filter_bounds = page.evaluate("testMap.getBounds().toBBoxString()")
        page.locator("#valid-only").check()
        count(1)
        assert page.evaluate("testMap.getBounds().toBBoxString()") == filter_bounds
        assert page.locator(".deal-card.selected").count() == 0
        page.locator("#valid-only").uncheck()
        count(3)
        date("2026-01-01")
        count(0)
        assert "No deals match this date/filter" in page.locator("#status").inner_text()
        # Freeze time while the browser uses a non-Singapore default timezone.
        page.clock.install(time=datetime.fromisoformat("2026-09-07T17:00:00+00:00"))
        page.locator("#today").click()
        count(3)
        assert page.locator("#as-of").input_value() == "2026-09-08"
        print("PASS server filters, empty date, Singapore Today")

        # Ignore abort signals deliberately so obsolete response protection is tested.
        older = snapshot()
        older["filters"]["as_of"] = "2026-08-09"
        older["deals"] = older["deals"][:1]
        newer = copy.deepcopy(older)
        newer["filters"]["as_of"] = "2026-08-18"
        newer["deals"] = snapshot()["deals"][1:]
        page.evaluate(
            """({older, newer}) => {
          window.realFetch = window.fetch;
          window.fetch = url => new Promise(resolve => {
            if (url.includes('2026-08-09')) window.finishOlder = () => resolve(new Response(JSON.stringify(older)));
            else resolve(new Response(JSON.stringify(newer)));
          });
        }""",
            {"older": older, "newer": newer},
        )
        date("2026-08-09")
        assert page.locator(".deal-card").count() == 0
        date("2026-08-18")
        count(2)
        page.evaluate(
            "async () => { finishOlder(); await new Promise(resolve => setTimeout(resolve, 0)); }"
        )
        assert page.locator("#as-of").input_value() == "2026-08-18"
        assert page.locator(".deal-card").count() == 2
        page.evaluate("() => { window.fetch = window.realFetch; }")
        print("PASS late response cannot overwrite newer filters")

        mode["api_error"] = True
        date("2026-08-26")
        page.locator("#retry").wait_for(state="visible")
        assert "Dataset unavailable" in page.locator("#status").inner_text()
        assert page.locator(".deal-card").count() == 0
        assert page.locator(".deal-pin").count() == 0
        mode["api_error"] = False
        page.locator("#retry").click()
        count(3)
        mode["tile_error"] = True
        page.reload()
        count(3)
        page.locator("#map-error").wait_for(state="visible")
        page.locator(".card-select").first.click()
        assert selected() == "deal-0"
        mode["tile_error"] = False
        page.locator("#retry-map").click()
        page.locator("#map-error").wait_for(state="hidden")
        print("PASS API and tile failures recover; selection works without tiles")

        mode["unmapped"] = True
        page.reload()
        count(0)
        assert "No mapped locations yet" in page.locator("#status").inner_text()
        mode["unmapped"] = False
        mode["no_map"] = True
        page.reload()
        count(3)
        assert "Map assets are unavailable" in page.locator("#map-error").inner_text()
        page.locator(".card-select").first.click()
        assert selected() == "deal-0"
        mode["no_map"] = False
        page.reload()
        count(3)
        print("PASS empty dataset and missing Leaflet fallback")

        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#show-all").click()
        count(3)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator("#map").bounding_box()["height"] >= 280
        assert page.locator(".leaflet-control-attribution").is_visible()
        page.locator(".card-select").first.focus()
        page.locator(".card-select").first.press("Space")
        assert selected() == "deal-0"
        assert not errors, errors
        print("PASS narrow layout, resize, keyboard selection; no JavaScript errors")
        context.close()
        browser.close()


if __name__ == "__main__":
    run()
