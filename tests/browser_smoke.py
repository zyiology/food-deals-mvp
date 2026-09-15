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
                "meal_types": [["lunch"], ["dinner"], ["lunch", "snack"]][index],
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
        "filters": {
            "as_of": "2026-08-26",
            "validity": "all",
            "meal": None,
            "max_age_days": 60,
        },
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
        custom_rows = None

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
                if custom_rows is not None:
                    data["deals"] = copy.deepcopy(custom_rows)
                params = parse_qs(url.query)
                data["filters"]["as_of"] = params.get("as_of", ["2026-08-26"])[0]
                data["filters"]["validity"] = params.get("validity", ["all"])[0]
                data["filters"]["meal"] = params.get("meal", [None])[0]
                if data["filters"]["meal"]:
                    data["deals"] = [
                        row
                        for row in data["deals"]
                        if data["filters"]["meal"] in row["meal_types"]
                    ]
                if data["filters"]["validity"] == "valid":
                    data["deals"] = data["deals"][:1]
                if data["filters"]["as_of"] == "2026-01-01" or mode["unmapped"]:
                    data["deals"] = []
                if mode["unmapped"]:
                    data["processing_summary"]["published_rows"] = 0
                route.fulfill(json=data)
            elif url.path == "/api/locations":
                route.fulfill(
                    json={
                        "results": [
                            {
                                "label": "Venue 0",
                                "address": "Venue 0, Singapore 123456",
                                "postal_code": "123456",
                                "latitude": 1.43,
                                "longitude": 103.95,
                            }
                        ]
                    }
                )
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

        def refresh(expected):
            # Dispatch without stealing focus from the control under inspection.
            with page.expect_response(lambda response: "/api/deals" in response.url):
                page.locator("#as-of").dispatch_event("change")
            count(expected)
            # Leaflet removes old popup DOM after its fade-out transition.
            expect(page.locator('.leaflet-popup[style*="opacity: 0"]')).to_have_count(0)

        def remember_focus():
            page.evaluate("""() => {
                window.savedControl = document.activeElement;
                window.savedPanelScroll = document.querySelector('.offers').scrollTop;
            }""")

        def same_focus():
            assert page.evaluate("document.activeElement === savedControl")

        def selected():
            return page.locator(".deal-card.selected").get_attribute("data-deal-id")

        def map_view(lat, lng, zoom):
            page.evaluate(
                "([lat, lng, zoom]) => testMap.setView([lat, lng], zoom, {animate: false})",
                [lat, lng, zoom],
            )

        popup_page = context.new_page()
        popup_page.set_default_timeout(5000)
        popup_page.goto(ORIGIN)
        popup_page.locator('[name="day"][value="custom"]').check()
        popup_page.locator("#welcome-date").fill("2026-08-26")
        popup_page.locator("#welcome-area").fill("123456")
        popup_page.locator("#welcome-suggestions li[role=option]").click()
        popup_page.locator("#welcome-submit").click()
        popup_page.wait_for_function(
            "document.querySelectorAll('.deal-card').length === 1 && "
            "document.querySelector('#deal-list').getAttribute('aria-busy') === 'false'"
        )
        assert "meal=lunch" in api_requests[-1]
        assert "as_of=2026-08-26" in api_requests[-1]
        assert "validity=valid" in api_requests[-1]
        assert popup_page.locator("#as-of").input_value() == "2026-08-26"
        assert popup_page.locator("#valid-only").is_checked()
        assert popup_page.locator("#meal-filter").input_value() == "lunch"
        expect(popup_page.locator("#open-welcome")).to_have_text("Find deals")
        expect(popup_page.locator("#selected-area")).to_have_text("Near Venue 0")
        assert popup_page.evaluate(
            "testMap.getCenter().distanceTo([1.43, 103.95]) < 1"
        )
        popup_page.locator("#open-welcome").click()
        assert popup_page.locator('[name="meal"][value="lunch"]').is_checked()
        assert popup_page.locator('[name="day"][value="custom"]').is_checked()
        assert popup_page.locator("#welcome-date").input_value() == "2026-08-26"
        popup_page.close()
        print("PASS popup meal, date and selected location drive the deals request")

        page.goto(ORIGIN)
        page.locator("#close-welcome").click()
        count(3)
        assert page.locator("#as-of").input_value() == "2026-08-26"
        assert not page.locator("#valid-only").is_checked()
        assert page.locator(".pin-number").all_text_contents() == ["1", "2"]
        assert page.locator(".number").all_text_contents() == ["1", "2"]
        assert page.locator(".leaflet-control-attribution").is_visible()
        assert page.locator(".validity.unknown").inner_text() == "Validity unknown"
        assert "End date not stated" in page.locator(".deal-card").first.inner_text()
        expect(page.locator("#count")).to_have_text(
            "3 deals at 2 locations in this view"
        )
        page.locator("#meal-filter").select_option("snack")
        count(1)
        assert "meal=snack" in api_requests[-1]
        page.locator("#meal-filter").select_option("")
        count(3)
        expect(page.locator(".pin-badge")).to_have_text("2 deals")
        assert page.locator(".deal-card .number, .popup-choices").count() == 0
        assert page.locator(".details[open]").count() == 0
        for disclosure in page.locator(".group-disclosure").all():
            expect(disclosure).to_have_attribute("aria-expanded", "true")
            target = page.locator("#" + disclosure.get_attribute("aria-controls"))
            expect(target).to_have_attribute(
                "aria-labelledby", disclosure.get_attribute("id")
            )
        print("PASS initial grouping, disclosures, counts, metadata, attribution")

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
        assert page.locator(".location-group .number").all_text_contents() == ["1"]
        assert page.locator(".pin-number").all_text_contents() == ["1"]
        assert len(api_requests) == request_count
        expect(page.locator(".leaflet-popup-close-button")).to_have_count(1)
        page.locator(".leaflet-popup-close-button").click()
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        page.locator(".deal-pin.active").press("Enter")
        expect(page.locator(".leaflet-popup-content strong")).to_have_text(
            "1. Shared map location"
        )
        assert selected() == "deal-1"
        expect(page.locator(".group-disclosure")).to_be_focused()
        page.locator(".card-select").nth(1).press("Enter")
        assert selected() == "deal-2"
        expect(page.locator(".deal-card.selected .card-select")).to_be_focused()
        map_view(1.43, 103.95, 15)
        count(1)
        assert page.locator(".deal-card.selected").count() == 0
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        map_view(1.2, 103.6, 15)
        count(0)
        assert "No matching deals in this area" in page.locator("#status").inner_text()
        page.locator("#show-all").click()
        count(3)
        print("PASS local viewport filtering, stable selection, shared pin, empty area")

        shared = page.locator('[data-coordinate-key="1.3,103.8"]')
        disclosure = shared.locator(".group-disclosure")
        offer = page.locator('[data-deal-id="deal-1"]')
        shared_pin = page.locator('.deal-pin[aria-label*="Shared map location"]')
        # A location alone must not select an arbitrary deal.
        shared_pin.press("Space")
        assert page.locator(".deal-card.selected").count() == 0
        expect(disclosure).to_be_focused()
        expect(shared.locator(".group-context")).to_have_text("Active location")
        disclosure.press("Enter")
        expect(disclosure).to_have_attribute("aria-expanded", "false")
        expect(shared.locator(".group-deals")).to_be_hidden()
        page.get_by_role("button", name="View deals", exact=True).click()
        expect(disclosure).to_be_focused()
        expect(disclosure).to_have_attribute("aria-expanded", "true")
        expect(page.locator(".leaflet-popup-content strong")).to_have_text(
            "2. Shared map location"
        )

        offer.locator(".card-select").click()
        disclosure.press("Space")
        expect(shared.locator(".group-context")).to_contain_text(
            "Contains selected offer"
        )
        page.get_by_role("button", name="Read offer details").click()
        expect(disclosure).to_have_attribute("aria-expanded", "true")
        expect(offer.locator("summary")).to_be_focused()
        expect(offer.locator("details")).to_have_attribute("open", "")
        disclosure.click()
        page.get_by_role("button", name="View all 2 deals here").click()
        expect(disclosure).to_be_focused()
        assert selected() == "deal-1"
        expect(page.locator(".leaflet-popup-content strong")).to_have_text("2. Offer 1")

        # In-place popup and details reconciliation must retain the same controls.
        page.get_by_role("button", name="Read offer details").focus()
        remember_focus()
        map_view(1.30, 103.80, 15)
        count(2)
        same_focus()
        expect(page.locator(".leaflet-popup-content strong")).to_have_text("1. Offer 1")
        expect(shared_pin).to_have_attribute(
            "title", "Location 1: Shared map location; 2 deals; active location"
        )
        expect(shared_pin).to_have_attribute("alt", shared_pin.get_attribute("title"))
        offer.locator("summary").focus()
        remember_focus()
        page.evaluate("testMap.panBy([5, 0], {animate: false})")
        same_focus()
        assert page.evaluate(
            "document.querySelector('.offers').scrollTop === savedPanelScroll"
        )
        expect(offer.locator("details")).to_have_attribute("open", "")
        shared_pin.press("Enter")
        assert selected() == "deal-1"
        page.get_by_role("button", name="View deals", exact=True).focus()
        remember_focus()
        page.evaluate(
            "testMap.fitBounds([[1.43, 103.95], [1.30, 103.80]], {padding: [40,40], maxZoom: 15, animate: false})"
        )
        count(3)
        same_focus()
        expect(page.locator(".leaflet-popup-content strong")).to_have_text(
            "2. Shared map location"
        )
        page.locator(".leaflet-popup-close-button").click()
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        page.evaluate("testMap.panBy([5, 0], {animate: false})")
        refresh(3)
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        assert selected() == "deal-1"
        print("PASS collapse navigation, popup modes, dismissal, renumbering and focus")

        # A new latest member forces the surviving group (and its focused card) to move.
        offer.locator("summary").focus()
        remember_focus()
        page.evaluate(
            "window.savedGroup = document.querySelector('[data-coordinate-key=\"1.3,103.8\"]')"
        )
        custom_rows = snapshot()["deals"]
        custom_rows[2]["posted_at"] = "2026-08-27T10:00:00+08:00"
        refresh(3)
        same_focus()
        assert page.locator(".location-group").first.evaluate("el => el === savedGroup")
        expect(offer.locator("details")).to_have_attribute("open", "")
        assert page.evaluate(
            "document.querySelector('.offers').scrollTop === savedPanelScroll"
        )
        disclosure.click()
        refresh(3)
        expect(disclosure).to_have_attribute("aria-expanded", "false")
        map_view(1.43, 103.95, 15)
        count(1)
        map_view(1.30, 103.80, 15)
        count(2)
        expect(disclosure).to_have_attribute("aria-expanded", "false")
        shared_pin.press("Enter")
        expect(disclosure).to_have_attribute("aria-expanded", "true")

        # Removing a selected member retains the location and changes only an open deal popup.
        offer.locator(".card-select").click()
        disclosure.click()
        custom_rows = snapshot()["deals"][2:]
        refresh(1)
        assert page.locator(".deal-card.selected").count() == 0
        expect(disclosure).to_have_attribute("aria-expanded", "false")
        expect(page.locator(".leaflet-popup-content strong")).to_have_text("1. Venue 2")
        expect(
            page.get_by_role("button", name="View deals", exact=True)
        ).to_be_visible()
        expect(shared.locator(".group-context")).to_have_text("Active location")
        expect(page.locator("#count")).to_have_text("1 deal at 1 location in this view")
        expect(page.locator(".pin-badge")).to_have_count(0)
        page.locator(".deal-pin").press("Enter")
        assert selected() == "deal-2"
        expect(page.locator(".card-select")).to_be_focused()
        expect(page.locator("details")).to_have_attribute("open", "")

        # Location mode remains location mode when its selected member becomes the sole deal.
        custom_rows = snapshot()["deals"][1:]
        refresh(2)
        offer.locator(".card-select").click()
        shared_pin.press("Enter")
        custom_rows = snapshot()["deals"][1:2]
        refresh(1)
        assert selected() == "deal-1"
        expect(page.locator(".leaflet-popup-content strong")).to_have_text("1. Venue 1")
        expect(
            page.get_by_role("button", name="View deals", exact=True)
        ).to_be_visible()
        page.locator(".leaflet-popup-close-button").click()
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        custom_rows = snapshot()["deals"][2:]
        refresh(1)
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        assert page.locator(".deal-card.selected").count() == 0

        # Focus falls back to the group for a removed card, or the list for a removed group.
        custom_rows = snapshot()["deals"][1:]
        refresh(2)
        offer.locator(".card-select").click()
        offer.locator("summary").focus()
        custom_rows = snapshot()["deals"][2:]
        refresh(1)
        expect(disclosure).to_be_focused()
        page.get_by_role("button", name="View deals", exact=True).focus()
        custom_rows = []
        refresh(0)
        expect(page.locator("#count")).to_be_focused()
        expect(page.locator(".leaflet-popup")).to_have_count(0)
        custom_rows = snapshot()["deals"]
        refresh(2)
        expect(disclosure).to_have_attribute("aria-expanded", "true")
        custom_rows = None
        page.locator("#show-all").click()
        count(3)
        print(
            "PASS group movement, collapse retention, membership transitions and focus fallback"
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
        assert "No matching deals" in page.locator("#status").inner_text()
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
        assert page.locator("#deal-list").get_attribute("aria-busy") == "true"
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
        page.locator("#close-welcome").click()
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
        page.locator("#close-welcome").click()
        count(0)
        assert "No mapped locations yet" in page.locator("#status").inner_text()
        mode["unmapped"] = False
        mode["no_map"] = True
        page.reload()
        page.locator("#close-welcome").click()
        count(3)
        assert "Map assets are unavailable" in page.locator("#map-error").inner_text()
        expect(page.locator("#count")).to_have_text(
            "3 deals at 2 locations in the list"
        )
        expect(page.locator(".location-group")).to_have_count(2)
        page.locator(".card-select").first.click()
        assert selected() == "deal-0"
        mode["no_map"] = False
        page.reload()
        page.locator("#close-welcome").click()
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
        page.locator(".deal-pin").nth(1).press("Enter")
        popup_box = page.locator(".leaflet-popup").bounding_box()
        map_box = page.locator("#map").bounding_box()
        assert popup_box["x"] >= map_box["x"]
        assert popup_box["x"] + popup_box["width"] <= map_box["x"] + map_box["width"]
        print("PASS narrow layout, resize, popup containment and keyboard selection")

        # Large numbers/counts and long shared building labels remain readable on both layouts.
        custom_rows = []
        template = snapshot()["deals"][0]
        for index in range(104):
            row = copy.deepcopy(template)
            row.update(
                deal_id=f"single-{index:03}",
                latitude=1.25 + index * 0.001,
                longitude=103.80,
                image_url=None,
            )
            custom_rows.append(row)
        for index in range(120):
            row = copy.deepcopy(template)
            row.update(
                deal_id=f"shared-{index:03}",
                latitude=1.30,
                longitude=103.86,
                posted_at="2026-08-01T10:00:00+08:00",
                image_url=None,
                resolved_label="A long shared building name with multiple entrances and shopping levels "
                * 3,
                merchant=f"Merchant {index}",
                unit=f"01-{index:03}",
            )
            custom_rows.append(row)
        with page.expect_response(lambda response: "/api/deals" in response.url):
            page.locator("#as-of").dispatch_event("change")
        expect(page.locator("#deal-list")).to_have_attribute("aria-busy", "false")
        page.locator("#show-all").click()
        count(224)
        large = page.locator('[data-coordinate-key="1.3,103.86"]')
        expect(large.locator(".number")).to_have_text("105")
        expect(large.locator(".group-count")).to_have_text("120 deals")
        expect(page.locator(".pin-badge")).to_have_text("120 deals")
        expect(page.locator("#count")).to_have_text(
            "224 deals at 105 locations in this view"
        )
        for width, height in [(1440, 1000), (375, 812)]:
            page.set_viewport_size({"width": width, "height": height})
            page.locator("#show-all").click()
            count(224)
            large.locator(".group-disclosure").focus()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            pin = page.locator('.deal-pin[aria-label^="Location 105:"]')
            number_box = pin.locator(".pin-number").bounding_box()
            badge_box = pin.locator(".pin-badge").bounding_box()
            assert number_box["x"] + number_box["width"] <= badge_box["x"]
            assert pin.locator(".pin-number").evaluate(
                "el => el.scrollWidth <= el.clientWidth"
            )
            page.screenshot(path=f"/tmp/location-grouping-{width}.png")
        print(
            "PASS long labels, 105 locations, 120-deal badge and desktop/mobile layout"
        )

        # A submitted location must win over a delayed initial snapshot fit.
        custom_rows = None
        page.add_init_script("""const realFetch = window.fetch;
            window.fetch = (url, options) => url === '/api/deals'
                ? new Promise(resolve => {
                    window.finishInitial = data => resolve(new Response(JSON.stringify(data)));
                  })
                : realFetch(url, options);""")
        page.reload()
        page.locator("#close-welcome").click()
        page.wait_for_function("window.finishInitial && window.testMap")
        page.evaluate(
            "window.dispatchEvent(new CustomEvent('welcome:location', {detail: {latitude: 1.30, longitude: 103.80, meal: 'dinner', asOf: '2026-08-26'}}))"
        )
        page.evaluate("data => finishInitial(data)", snapshot())
        count(1)
        assert page.evaluate("testMap.getZoom()") == 14
        assert page.evaluate("testMap.getCenter().distanceTo([1.30, 103.80]) < 1")
        assert not errors, errors
        print("PASS submitted-location precedence; no JavaScript errors")
        context.close()
        browser.close()


if __name__ == "__main__":
    run()
