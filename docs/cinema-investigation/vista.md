# Vista HTML group (adapter B): Universal Cinemas, CineStar

Source: [cinema viability audit](../cinema-viability-audit.md) (2026-11-23), re-checked 2026-11-25 with `scripts/snapshot_evidence.py`.

## Universal Cinemas

| Field | Content |
|---|---|
| Data source | html: server-rendered Vista pages on `https://universalcinemas.com`. `/browsing/Cinemas/Details/<branch>` lists films and sessions (`<time datetime>`). No XHR/JSON for showtimes. |
| Login or CAPTCHA? | No |
| Showtime horizon | 4–5 days ahead |
| Seat data | None in the listing; would need the ticketing flow. Not pursued. |
| Branches | Emporium Mall, Lahore `8888` (in this draft); The Grand Mall, Multan `9999` (not yet investigated) |
| Booking link | `/Ticketing/visSelectTickets.aspx?cinemacode=<branch>&txtSessionId=<sessionId>` (seen in the session links of the details page, 2026-11-28) |
| Branch coordinates | Emporium Mall `[74.26677349646782, 31.467151031607372]` (map, by hand) |
| Robots evidence | `/robots.txt` redirects (→ `/browsing/robots.txt` → `/Browsing/General/Error`) to an HTML error page served as HTTP 200. That is a soft 404, so treated as missing → allow all. `/browsing/Cinemas`, `/browsing/Cinemas/Details/8888`, `/browsing/Movies/NowShowing` Allowed (2026-11-25). |
| Terms | `https://universalcinemas.com/browsing/General/TermsAndConditions` (sha256 `f802691c…8b8b206`, 2026-11-25). Ticketing terms only; nothing on automated access found (audit 2026-11-23; owner re-read 2026-11-25: no such clause). |
| Verdict | **Allowed** |
| Technical verdict | **Go** (runner probe passed 2026-11-25) |
| Effort | M (HTML parsing; same adapter serves CineStar) |

### Adapter notes

- If the site ever serves a real robots.txt, the canary sees the hash change from `null` and re-evaluation is required.
- The canary must check the expected page structure: a hijacked or changed domain must show as drift, never be published.

## CineStar

Use `cinestar.pk` only; the old `cinestar.com.pk` domain is a gambling site.

| Field | Content |
|---|---|
| Data source | html: same Vista pages as Universal on `https://cinestar.pk`; `/browsing/Cinemas/Details/<branch>` |
| Login or CAPTCHA? | No |
| Showtime horizon | 3–4 days ahead (audit: sessions 23–26 Nov) |
| Seat data | None in the listing. Not pursued. |
| Branches | Township, Lahore `0005` (in this draft; name confirmed on the page 2026-11-25); Xinhua Mall, Lahore `0001`; `0002`; Xin Mall, Sargodha `0000000006` |
| Booking link | Same Vista pattern: `https://cinestar.pk/Ticketing/visSelectTickets.aspx?cinemacode=0005&txtSessionId=<id>` (seen in the session links, 2026-11-28) |
| Branch coordinates | Township `[74.31080216763247, 31.450402964635277]` (map, by hand) |
| Robots evidence | `/robots.txt` redirects to an HTML error page served as HTTP 200 → soft 404 → allow all. `/browsing/Cinemas`, `/browsing/Cinemas/Details/0005` Allowed (2026-11-25). |
| Terms | `https://cinestar.pk/browsing/General/TermsAndConditions` (sha256 `7c6220b7…2d11d8080`, 2026-11-25). Ticketing terms; nothing on automated access found (audit 2026-11-23; owner re-read 2026-11-25: no such clause). |
| Verdict | **Allowed** |
| Technical verdict | **Go** (runner probe passed 2026-11-25) |
| Effort | S (reuses the Universal adapter) |

## Adapter (P2-01, `scraper/src/moviespk_scraper/adapters/vista.py`)

One GET per branch per run: `/browsing/Cinemas/Details/<branch>` (fixtures captured 2026-11-28 in `scraper/tests/fixtures/<cinema>/2026-11-28/`).

| Item | Source on the page |
|---|---|
| Film | `div.film-list > div.film-item` with `data-movie-id` (local key) and `h3.film-title`; items without `a.session-time` are coming soon and skipped |
| Rating | `img.rating-image` src `…/RatingIconGraphic/<rating>` (M, U, G, PG, R as published) |
| Start time | `a.session-time > time[datetime]`, naive PKT. A show after midnight is listed under the previous evening's `h4.session-date` heading, but `datetime` already has the real date (Sanjog `2026-11-29T00:00` under "Saturday, 28 November 2026"). A `datetime` that is neither the heading's date nor the early hours of the next day is drift. |
| Session id | `txtSessionId` in the session link; its `cinemacode` must equal the branch |
| Hall, format, language | the session's icon `img[alt]`: `3DX` → 3D (Universal's 3D branding), `Urdu`/`Japanese`/… → language, anything else is the hall (`Screen-9`, `Gold`, `Diamond 11`, `SUPER ULTRA`, `Screen 1`…) |

Drift (`SchemaDriftError`, page saved as `cinema-details.html`): non-200, no `div.film-list` or `div.film-item`, a film with sessions but no id or title, a session without `txtSessionId` or a parseable naive `datetime`, an unparseable heading, another cinema's code.

Live dry runs 2026-11-28: Universal 23 films / 97 shows, CineStar 9 films / 20 shows, 0 invalid. Both enabled.

## Runner reachability (P0-09)

2026-11-25T13:19Z, GitHub-hosted `ubuntu-latest`, real User-Agent, one GET per venue after robots.txt. (robots.txt 200 is the HTML error page after redirects, i.e. the soft 404.)

| Venue | robots.txt | Main GET | Bytes | Challenge page | Result |
|---|---|---|---|---|---|
| `universal-emporium-mall-lahore` (`/browsing/Cinemas/Details/8888`) | 200 (soft 404) | 200 | 174783 | no | reachable |
| `cinestar-township-lahore` (`/browsing/Cinemas/Details/0005`) | 200 (soft 404) | 200 | 64699 | no | reachable |
