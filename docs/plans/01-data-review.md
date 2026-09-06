# Source data review

Reviewed on 2026-09-06. This is an inspection of the local exports, not verification that the advertised promotions remain available. See [the overall plan](README.md) for proposed scope and phase order.

## Repository baseline

- [The draft](../../mvp_draft.md) proposes a local FastAPI application, vanilla JavaScript with Leaflet, OpenRouter extraction, Nominatim geocoding, and JSON storage.
- [The notes](../../thoughts.md) require a separate normalized deal for each location, nullable start/end dates with no expiry when the end is unknown, and ephemeral viewport numbering.
- [README.md](../../README.md) is empty. The Python package contains only a greeting entry point. Python requires 3.14 or later; `uv` manages tooling. Ruff is declared, but FastAPI, HTTP/model validation libraries, pytest, and ty are not yet declared.
- There is no application, preprocessing pipeline, existing test suite, or established data contract to preserve. The working tree consists of untracked initial project files at review time.

## Measured inventory

Counts were calculated from each `result.json` and its referenced files. All messages and captions were inspected programmatically; three representative photos were inspected visually. No linked promotion pages were fetched, no LLM extraction was run, and no geocoding quality measurement was performed.

| Export | Channel ID | Records | `message` records | Pin-service records | Existing photos | Omitted video/animation files |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| [GoodLobang](../../Telegram_AUG_2026/GoodLobang_AUG_2026/result.json) | 1216422279 | 49 | 48 | 1 | 46 | 2 videos |
| [KiasuFoodies](../../Telegram_AUG_2026/KiasuFoodies_AUG_2026/result.json) | 1329056215 | 40 | 39 | 1 | 39 | 0 |
| [SGFoodDeals](../../Telegram_AUG_2026/SGFoodDeals_AUG_2026/result.json) | 1204657101 | 50 | 50 | 0 | 47 | 2 animations |
| **Total** | | **139** | **137** | **2** | **132** | **4** |

SGFoodDeals message 4889 is an empty-caption poll. Excluding it and the two service records leaves **136 text-bearing posts eligible for semantic classification**, not 136 confirmed food deals. Of these, 132 have photos and four retain captions despite omitted media. Photo files total 22,691,998 bytes, approximately 21.6 MiB; none are byte-identical. No exact duplicate full captions were found, but related promotions recur across channels.

Dates span August 1–31, 2026 overall. Every record's Unix timestamp agrees with its timezone-free `date` when converted to `Asia/Singapore`. All 137 `message` records include edit timestamps. Message IDs are unique within each export; the channel ID must still be part of the identity.

## Findings that affect implementation

| Observed case | Evidence: channel / message ID | Planning consequence |
| --- | --- | --- |
| Mixed Telegram text representation | 136 list-valued captions; the poll and two service records use empty strings | Concatenate string fragments and entity `text` in order; preserve the original representation for traceability. |
| Hidden link destinations | KiasuFoodies has 38 `text_link` entities, frequently labelled “here” | Extract entity `href` separately; flattening visible text loses these URLs. Avoid duplicating captions by concatenating both `text` and `text_entities`. |
| Media export placeholders | GoodLobang 4614/4618; SGFoodDeals 4907/4909 | Treat “File not included…” as an unavailable attachment, not a filesystem path or fatal post error. |
| Non-food ads inside source channels | GoodLobang 4602 hair care, 4609 slimming, 4621 electricity; SGFoodDeals 4869 home renovation | Food relevance needs semantic classification. A channel name, hashtag, or location emoji cannot establish relevance. |
| Online-only food offers | SGFoodDeals 4871; KiasuFoodies 5253/5272 | Preserve food relevance separately from physical-location eligibility. Delivery apps are not map coordinates. |
| Unspecified branch sets | GoodLobang 4604 “All outlets excl. NTU & NUS”; KiasuFoodies 5274 “10 participating outlets” | Geocoding cannot discover participating branches from these phrases. Preserve scope and exclusions; measure this coverage gap. |
| Multiple locations, different dates | GoodLobang 4623; SGFoodDeals 4883 | Jewel Changi Airport and Waterway Point need their own availability. Do not take a Cartesian product of all dates and locations. |
| Multiple promotions at one place | SGFoodDeals 4904 | Geláre ice cream, drinks, and croffles have three different periods. One post is not necessarily one offer. |
| Multiple promotions with overlapping periods | KiasuFoodies 5257 | Gotcha's free-drink promotion and 1-for-1 promotion need distinct offer records. |
| Separate dates | GoodLobang 4607; KiasuFoodies 5282; SGFoodDeals 4901 | “Today & 12 Aug” and “22, 23, 29, 30 Aug” must not silently become continuous availability. |
| Recurring and conditional availability | GoodLobang 4608/4629/4642; SGFoodDeals 4887/4912 | Weekdays, time windows, holidays, membership, and redemption limits are different from expiry. Preserve restrictions even when not machine evaluated. |
| Broad place versus specific site | KiasuFoodies 5264 “Lengkok Bahru”; SGFoodDeals 4900 “Bugis #03-08” | A plausible neighborhood centroid is not evidence of the right outlet. Ambiguous locations need review. |
| Named building in prose | SGFoodDeals 4858 City Square Mall; 4883 dates identify locations without a pin emoji | Extract from the whole caption, not only `📍` lines. |
| Unit numbers and shared coordinates | GoodLobang 4620; SGFoodDeals 4877; several 313 Orchard Road posts | Preserve units for display while allowing building-level geocoding. Multiple deal markers can overlap. |
| Roundups and sparse recommendations | SGFoodDeals 4864/4876/4879/4882/4910 | Split only supported offers; do not invent addresses or specific terms for summaries. Some will remain unmapped or require review. |
| Same campaign with differing detail | Burnt Cones: GoodLobang 4620, KiasuFoodies 5270, SGFoodDeals 4877 | Keep source records separate initially. Automatic merging could discard differing conditions or dates. |
| Footer mentions unrelated to source | SGFoodDeals 4908/4912 advertise other channels; 4909 ends with `@sgfooddealssg` | Configure each source channel's public username explicitly; do not choose the last mention as its identity. |

A literal phrase scan found 39 posts containing “all outlets” or “all Tai Cheong outlets”, and four containing “selected outlets”. These are not exhaustive scope counts: “most outlets”, “all operating outlets”, and numbered participating-outlet phrases occur too. Similarly, 110 posts contain `📍`, but this does not establish a resolvable physical location or food relevance.

## What the photo sample establishes

- KiasuFoodies 5255's MILO image advertises eight events but does not list their venues. Image processing will not automatically resolve every caption gap.
- KiasuFoodies 5274's Greendot image adds a collection window of 11:00–11:30, while the caption says 10:00 onwards. The caption alone does not capture all redemption conditions.
- SGFoodDeals 4904's Geláre image is a promotional collage; the caption carries the three distinct offer periods.

This small sample does not establish image-wide extraction accuracy or the proportion of missing addresses recoverable from images. A later image pilot should measure added coverage and conflicts against the text baseline.

## Suggested evaluation slice

Use approximately 20–25 posts covering the cases above, including both clearly mappable and deliberately unmappable examples. Record human expectations for relevance, offer splitting, location/date associations, source links, and location precision. Include examples not used in the prompt when checking model quality.

Report a funnel with explicit denominators: 139 raw records → 136 text candidates → classified relevant posts → extracted offers → explicit location candidates → accepted mapped rows. Also report exclusions, unresolved cases, processing failures, and duplicate campaign candidates separately. Actual values after the first two stages are unknown until implementation and evaluation.

Do not judge usefulness solely on today's active deals: much of this historical sample has expired. Evaluate at selected August dates and at the current Singapore date, with the selected date visible in the UI.
