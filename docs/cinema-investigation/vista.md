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
| Booking link | `/Ticketing/visSelectTickets.aspx?cinemacode=<branch>&txtSessionId=<sessionId>` (from the audit; owner to confirm with one click) |
| Branch coordinates | Emporium Mall `[74.26677349646782, 31.467151031607372]` (map, by hand) |
| Robots evidence | `/robots.txt` redirects (→ `/browsing/robots.txt` → `/Browsing/General/Error`) to an HTML error page served as HTTP 200. That is a soft 404, so treated as missing → allow all. `/browsing/Cinemas`, `/browsing/Cinemas/Details/8888`, `/browsing/Movies/NowShowing` Allowed (2026-11-25). |
| Terms | `https://universalcinemas.com/browsing/General/TermsAndConditions` (sha256 `f802691c…8b8b206`, 2026-11-25). Ticketing terms only; nothing on automated access found (audit 2026-11-23; owner re-read: **pending**). |
| Verdict | **Allowed** |
| Technical verdict | **Go** (pending the P0-09 runner probe) |
| Effort | M (HTML parsing; same adapter serves CineStar) |

### Adapter notes

- If the site ever serves a real robots.txt, the canary sees the hash change from `null` and re-evaluation is required.
- The canary must check the expected page structure: a hijacked or changed domain must show as drift, never be published.

## CineStar

Not investigated yet (audit candidate #5: CineStar Township, Lahore, `cinestar.pk` only; the old `cinestar.com.pk` domain is a gambling site).

## Runner reachability (P0-09)

Not run yet.
