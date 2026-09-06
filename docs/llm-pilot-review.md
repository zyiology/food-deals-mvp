# Phase 2 pilot: annotation review

Status: **draft annotations awaiting user review; no paid evaluation has run**.

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

There are 21 development posts and nine held-out posts, with three held out from each channel. No pilot captions or answers are included as prompt examples. The fixture records the initial prompt, schema and settings hashes before evaluation; subsequent cache/recovery fixes have not changed the semantic prompt or schema. Keep held-out errors out of prompt tuning until the first score is recorded. If they inform later changes, call subsequent results **re-evaluation**, preserve the original errors, and include all additional spending.

Expected development counts are 24 offers / 17 location rows; held-out counts are 9 offers / 6 location rows. Count differences help locate errors but cannot establish correctness. Review each post against the full annotation. Order, wording and derived IDs need not match. Equivalent redundant boundaries around an unchanged exact-date set are acceptable; broadened gaps, lost weekdays or incorrect outlet/date associations are not.

For each source ID, record its raw cache fingerprint and uncorrected output, expected/actual offer and location counts, and each missing/extra benefit, location, date, classification or restriction. Assign a semantic-match verdict and explain any mismatch or unexpected review flag. Examine effective location schedules as well as common offer dates. Manual patches may make usable rows, but do not improve the original model score.

| Acceptance check | Required result | Current result |
| --- | --- | --- |
| Outcomes | All 30 recorded; no unresolved provider/schema failures | Not run |
| Critical correctness | Zero accepted invented benefits/places, excluded participants, non-food/online-only physical candidates, unsupported associations or wrong effective date constraints | Not run |
| Complete interpretation | At least 27/30, at least 9/10 in each channel, at least 8/9 held out | Not run |
| Mandatory edge cases | Every starred splitting, outlet-specific-date, separate-date, weekday and unknown-expiry case matches | Not run |
| Evidence | Every accepted benefit, location and asserted date has caption evidence; every mismatch is reported | Not run |
| Offline behavior | Reservation/recovery, locking, source validation, caching, retry and date checks pass | 134 tests, Ruff and ty pass |
| Human review | User reviews the full report, including allowed aggregate errors, before the remaining batch | Pending |

An expected review outcome counts as a completed interpretation when it matches the annotation. An unexpected review flag is safe but still an extraction error. Category labels `pure_listing` and `mixed_promotion` alone do not require review.

After annotation and criteria approval, follow the [operation guide](llm-processing.md) to run the pilot under the existing US$5 cap. Review the pilot results before creating the full-batch approval file or sending the remaining 106 posts.
