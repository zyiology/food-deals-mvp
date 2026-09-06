# Telegram Food Deals Map — MVP Plan

## Goal

Build a local web app that takes previously exported Telegram food-deal posts, identifies where each deal is located, geocodes those locations, and presents the deals on an interactive map.

The purpose of the MVP is to validate whether a location-based view of Telegram food deals is useful before investing in automated Telegram ingestion or production infrastructure.

## Proposed Stack

* **Backend:** FastAPI
* **Frontend:** Lightweight HTML/CSS/JavaScript served by FastAPI
* **Map:** Leaflet
* **Location extraction:** LLM through OpenRouter
* **Geocoding:** OpenStreetMap Nominatim
* **Storage:** Local normalized JSON files; no database initially
* **Source data:** Manually downloaded Telegram exports

## High-Level Data Flow

```text
Telegram export
      ↓
Preprocessing / enrichment
      ↓
LLM extracts location
      ↓
Nominatim converts location → coordinates
      ↓
Normalized deals dataset
      ↓
FastAPI
      ↓
Leaflet map + deal list
```

### 1. Preprocess Telegram data

Run a local preprocessing step over the downloaded Telegram export.

For each relevant message, produce a normalized deal containing the information needed by the application, such as:

* deal ID
* title / description
* source channel
* original posting date
* original Telegram content/link where available
* extracted location
* latitude / longitude
* optional image

This preprocessing runs separately from the web app.

### 2. Extract locations using an LLM

Send each deal's text to a relatively inexpensive model through OpenRouter.

The model's task should be deliberately narrow: identify the physical location associated with the deal, or return `null` when there is no sufficiently clear location.

Prefer structured output rather than free-form text where the selected model supports it.

LLM responses should be cached so that unchanged Telegram messages do not need to be processed repeatedly.

### 3. Geocode extracted locations

Pass extracted locations to Nominatim to obtain coordinates.

Geocoding should happen during preprocessing rather than when the web application is being viewed. Results should also be cached.

For the initial local MVP, the public Nominatim service is sufficient as long as its usage policy is respected: requests must be throttled, identified with an appropriate User-Agent, and cached. The public service permits at most one request per second and discourages repeated/bulk geocoding, so a different provider such as Google Places should be substituted if the project grows.

### 4. Serve the normalized dataset with FastAPI

FastAPI will provide:

* the local web application
* an endpoint returning normalized deals
* static frontend assets

There is no need for a database, authentication, background workers, or deployment infrastructure for the MVP.

### 5. Build the map interface

The page should have two main areas:

```text
┌────────────────────┬────────────────────────────────┐
│ Deals              │                                │
│                    │              Map               │
│ 1. Deal A          │                                │
│ 2. Deal B          │        2                       │
│ 3. Deal C          │                   1            │
│                    │             3                  │
│                    │                                │
└────────────────────┴────────────────────────────────┘
```

The main map uses Leaflet.

Each visible deal appears as a **numbered marker**. The left sidebar shows the corresponding numbered deal cards.

When the map is moved or zoomed:

1. determine which deals fall inside the current map bounds;
2. update the sidebar to show only those deals;
3. assign matching numbers to the visible map markers and sidebar items.

Selecting either a marker or sidebar item should highlight/show the corresponding deal.

The sidebar should initially display basic information such as the deal title, location, posting date, and a short description.

## MVP Scope

The first version should support:

* manually downloaded Telegram data
* LLM-based location extraction
* one-time/cached geocoding
* map markers
* viewport-aware deal sidebar
* interaction between sidebar items and markers
* basic filtering of old deals

It does **not** initially need:

* automatic Telegram scraping
* user accounts
* a database
* cloud deployment
* scheduled processing
* sophisticated search
* recommendation/ranking algorithms
* perfect location extraction
* production-scale geocoding

## MVP Success Criterion

The main question to answer is:

> Is it useful to open a map, look at an area of Singapore, and immediately see relevant food deals available around that area?

If the map feels useful with a relatively small set of recent Telegram posts, the next phase can focus on automated ingestion, better deal/expiry extraction, production storage, and more robust geocoding.

