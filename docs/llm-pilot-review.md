# Phase 2 pilot: annotation review

Status: **30-post paid pilot run completed on 2026-09-06; only the first five development entries have been compared; annotations remain draft**.

The local [extraction report](../data/reports/extract.json) records 34 offers and 22 explicit offer/location rows, with nine posts marked `success` and 21 `needs_review`. The [partial comparison report](../data/reports/llm-pilot-review-batch-01.json) covers SGFoodDeals 4858, 4870, 4883, 4884, and 4900: one match and four mismatches against the original draft expectations. The other 25 posts, including all nine held-out posts, remain unscored. These generated files are local artifacts ignored by Git.

This document preserves the original experiment and scoring protocol for reference. Its exhaustive acceptance gate is superseded by the approved [Phase 2 demo workflow](plans/03-llm-processing.md). Use `uv run food-deals-mvp review-demo` to inspect saved results as cards and select a small demo sample. The LLM response schema is retained; equivalent grouping and cosmetic evidence differences no longer fail demo review.

The [machine-readable fixture](../tests/fixtures/llm-pilot-annotations.json) contains all 30 captions, source links and input hashes, expected classifications, benefits, scopes/exclusions, material restrictions, exact evidence, and effective location schedules. The [pilot ID file](../config/llm-pilot-post-ids.json) selects exactly these posts. Labels were prepared by the assistant from captions; they are not yet human-approved ground truth.

The proposal contains **33 offers and 23 explicit offer/location rows**. These are expected extraction counts, not measured model outputs or accepted map pins. Food offers without explicit places remain internal. Two location-ambiguity cases and one promotion-taxonomy case are expected to require review.

## Decisions to review

1. **GoodLobang 4602, clear hair-care advertising:** relevance is `non_food`, with zero offers. The current promotion-kind enum has no non-food-promotion value; the draft uses `uncertain`, which currently causes a review flag. This reflects a taxonomy limitation, not doubt that the post is non-food. Confirm this conservative treatment or revise the taxonomy before evaluation.
2. **SGFoodDeals 4858, City Square Mall:** the proposed split is three food offers: $1 drinks (including the conditional flask gift), a $5 Food Republic voucher, and a $10 Canton Paradise/LeNu voucher. The generic CDL voucher and bag charm are excluded because no food benefit is stated. Minimum spend amounts and dates remain unspecified. The listed drinks are alternatives, not separate offers.
3. **Ambiguous places:** KiasuFoodies 5264 retains `Lengkok Bahru` without inventing an address. SGFoodDeals 4900 retains `Bugis` and `Northpoint` plus their supplied units, with review for the ambiguous Bugis building. Conservative review of both rows is acceptable under the current offer-level review schema.
4. **Food event listings:** SGFoodDeals 4884 has six dated events but no concrete price, sample, discount or redemption benefit. The draft labels it `pure_listing` with zero offers.

## Selection and expected results

**D** = development slice; **H** = held out. A star marks a mandatory edge case. All expected values below are proposals for review. The JSON fixture is authoritative for exact restrictions, supporting excerpts, and nullable fields.

| Source / message | Split | Offers / location rows | Expected interpretation |
| --- | --- | ---: | --- |
| [SGFoodDeals 4858](https://t.me/sgfooddeals/4858) | D | 3 / 3 | $1 drinks with optional additional flask-redemption gift; $5 Food Republic voucher with minimum spend at B2 shops; $10 Canton Paradise or LeNu e-voucher with minimum spend at B2 shops |
| [SGFoodDeals 4870](https://t.me/sgfooddeals/4870) | D | 1 / 0 | Up to 55% off snacks, drinks, eggs and other groceries |
| [SGFoodDeals 4871](https://t.me/sgfooddeals/4871) | H | 1 / 0 | Grocery sale from $2.80 |
| [SGFoodDeals 4881](https://t.me/sgfooddeals/4881) | H | 1 / 1 | Free Linguine al Limone by trading a lemon and buying another main |
| [SGFoodDeals 4883 ★](https://t.me/sgfooddeals/4883) | D | 1 / 2 | 1-for-1 selected yogurt shakes |
| [SGFoodDeals 4884](https://t.me/sgfooddeals/4884) | D | 0 / 0 | food / pure_listing; no offers |
| [SGFoodDeals 4900](https://t.me/sgfooddeals/4900) | D | 1 / 2 | 1-for-1 Soy Blend Series giveaway; needs review |
| [SGFoodDeals 4901 ★](https://t.me/sgfooddeals/4901) | D | 1 / 0 | $10 large pizza for takeaway or self-collection |
| [SGFoodDeals 4904 ★](https://t.me/sgfooddeals/4904) | D | 3 / 3 | 1-for-1 Single Scoop Ice Cream; 1-for-1 Coffee & Mocktails; 1-for-1 Croffles |
| [SGFoodDeals 4912 ★](https://t.me/sgfooddeals/4912) | H | 1 / 0 | $9.90 lunch set with free Wild Mushroom Soup |
| [GoodLobang 4602](https://t.me/goodlobang/4602) | D | 0 / 0 | non_food / uncertain; no offers; needs review |
| [GoodLobang 4604](https://t.me/goodlobang/4604) | D | 1 / 0 | Dice roll for up to 100% cashback |
| [GoodLobang 4606](https://t.me/goodlobang/4606) | H | 1 / 1 | 20% off large drinks |
| [GoodLobang 4607 ★](https://t.me/goodlobang/4607) | D | 1 / 0 | 20% off drinks |
| [GoodLobang 4611](https://t.me/goodlobang/4611) | D | 1 / 0 | 1-for-1 Root Beer Float |
| [GoodLobang 4623 ★](https://t.me/goodlobang/4623) | D | 1 / 2 | 1-for-1 selected yogurt shakes |
| [GoodLobang 4629 ★](https://t.me/goodlobang/4629) | D | 1 / 0 | $6.10 Chicken Burger, small fries and iced tea set |
| [GoodLobang 4633](https://t.me/goodlobang/4633) | D | 1 / 0 | Free soft drink with $5++ per hour karaoke package |
| [GoodLobang 4634 ★](https://t.me/goodlobang/4634) | H | 1 / 2 | $1.90++ Salmon Belly Sushi |
| [GoodLobang 4644 ★](https://t.me/goodlobang/4644) | H | 1 / 0 | Free crab half serving with Crab Sub purchase |
| [KiasuFoodies 5255](https://t.me/kiasufoodies/5255) | D | 1 / 0 | Free MILO on five listed dates |
| [KiasuFoodies 5256](https://t.me/kiasufoodies/5256) | H | 1 / 1 | 50% off selected dishes |
| [KiasuFoodies 5257 ★](https://t.me/kiasufoodies/5257) | D | 2 / 2 | Free 200 drinks; 1-for-1 drinks |
| [KiasuFoodies 5262](https://t.me/kiasufoodies/5262) | H | 1 / 0 | $0.61 mini croissants |
| [KiasuFoodies 5264](https://t.me/kiasufoodies/5264) | D | 1 / 1 | $6.10 for a 90-minute buffet; needs review |
| [KiasuFoodies 5269 ★](https://t.me/kiasufoodies/5269) | D | 1 / 1 | 1-for-1 weekday specials |
| [KiasuFoodies 5271](https://t.me/kiasufoodies/5271) | H | 1 / 1 | 1-for-1 Kaisendon |
| [KiasuFoodies 5272](https://t.me/kiasufoodies/5272) | D | 1 / 0 | Delivery meal from $9.90: one listed burger, Chicken McCrispy, fries and drink |
| [KiasuFoodies 5274](https://t.me/kiasufoodies/5274) | D | 1 / 0 | $1.50 Bento Set |
| [KiasuFoodies 5282 ★](https://t.me/kiasufoodies/5282) | D | 1 / 1 | $1 kombucha |

## Mandatory schedule checks

| Source / message | Expected effective dates |
| --- | --- |
| GoodLobang 4623 | Jewel: Aug 14–16; Waterway Point: Aug 17–19; preserve units B2-234 and 01-63 |
| SGFoodDeals 4883 | Jewel: Aug 14–16; Waterway Point: Aug 17–19; no units supplied in this caption |
| KiasuFoodies 5257 | Free 200 drinks: Aug 3–4; 1-for-1: Aug 3–9 |
| SGFoodDeals 4904 | Ice cream: Aug 26–30; coffee/mocktails: Aug 31–Sep 6; croffles: Sep 7–13, all at Westgate |
| GoodLobang 4607 | Exactly Aug 5 and 12 |
| KiasuFoodies 5282 | Exactly Aug 22, 23, 29 and 30 |
| SGFoodDeals 4901 | Exactly Aug 25, 26; Sep 1, 2, 8 and 9 |
| GoodLobang 4629 | Mondays and Tuesdays; both boundaries unspecified |
| KiasuFoodies 5269 | Tuesdays–Thursdays, through Aug 27; start unspecified |
| GoodLobang 4634 (held out) | Aug 20–28, weekdays only, at both listed locations |
| GoodLobang 4644 (held out) | From Aug 27; end unspecified |
| SGFoodDeals 4912 (held out) | Mondays–Fridays; both boundaries unspecified |

All dates use 2026 and inclusive boundaries. Posting-date exclusion still applies when the start boundary is null. Preserve time windows and other restrictions from the full fixture.

## Holdout and scoring protocol

The original experiment designated 21 development posts and nine held-out posts, with three held out from each channel. The fixture preserves the initial prompt, schema, and settings hashes. The demo workflow now uses a revised prompt and validation rules; inspecting the saved sample does not establish an independent holdout score. The following scoring rules are historical, not required demo approval steps.

Expected development counts are 24 offers / 17 location rows; held-out counts are 9 offers / 6 location rows. Count differences help locate errors but cannot establish correctness. Review each post against the full annotation. Order, wording and derived IDs need not match. Equivalent redundant boundaries around an unchanged exact-date set are acceptable; broadened gaps, lost weekdays or incorrect outlet/date associations are not.

For each source ID, record its raw cache fingerprint and uncorrected output, expected/actual offer and location counts, and each missing/extra benefit, location, date, classification or restriction. Assign a semantic-match verdict and explain any mismatch or unexpected review flag. Examine effective location schedules as well as common offer dates. Manual patches may make usable rows, but do not improve the original model score.

| Acceptance check | Required result | Current result |
| --- | --- | --- |
| Outcomes | All 30 recorded; no unresolved provider/schema failures | All 30 have parsed outputs; nine success, 21 needs_review |
| Critical correctness | Zero accepted invented benefits/places, excluded participants, non-food/online-only physical candidates, unsupported associations or wrong effective date constraints | Partial review found unsupported location/scope interpretations; not passed |
| Complete interpretation | At least 27/30, at least 9/10 in each channel, at least 8/9 held out | 1/5 reviewed matches; four mismatches exceed original allowance if upheld; 25 unscored |
| Mandatory edge cases | Every starred splitting, outlet-specific-date, separate-date, weekday and unknown-expiry case matches | 4883 mismatched under original grouping/evidence rules; other mandatory cases unscored |
| Evidence | Every accepted benefit, location and asserted date has caption evidence; every mismatch is reported | Malformed emoji evidence found in partial review; full review incomplete |
| Offline behavior | Reservation/recovery, locking, source validation, caching, retry and date checks pass | 134 tests, Ruff and ty pass |
| Human review | User reviews the full report, including allowed aggregate errors, before the remaining batch | Pending |

An expected review outcome counts as a completed interpretation when it matches the annotation. An unexpected review flag is safe but still an extraction error. Category labels `pure_listing` and `mixed_promotion` alone do not require review.

The initial pilot does not need to be run again merely to inspect it. The offline demo review preserves all original caches and findings. Additional live extraction can use `--accept-demo` instead of the old approval file, within the existing cumulative US$5 cap; the website demonstration can proceed using only a selected pilot subset.
