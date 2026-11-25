# Cinepax (adapter A: public JSON)

Source: [cinema viability audit](../cinema-viability-audit.md) (2026-11-23), re-checked 2026-11-25 with `scripts/snapshot_evidence.py`.

| Field | Content |
|---|---|
| Data source | json: `GET /api/cinemas` (branch list), `GET /api/movies?cinemaId=<branch>` (movies with sessions) on `https://web.cinepax.com` |
| Login or CAPTCHA? | No |
| Showtime horizon | 2–3 days ahead |
| Seat data | `seatsAvailable` count per session, inside the same `/api/movies` response (0 extra requests per show). Not enabled yet; decide under plan §10.6. |
| Branches | Packages Mall `0000000014`, World Trade Center `0000000011`, Ocean Mall `0000000002` (enabled in this draft); 7 more branches listed by `/api/cinemas` |
| Booking link | On-site booking; URL pattern not yet recorded (fill in P2-01) |
| Branch coordinates | See below; taken from a map by hand, `[lng, lat]` |
| Robots evidence | `/robots.txt` returns HTTP 404 → allow all (RFC 9309). `/api/cinemas` Allowed, `/api/movies` Allowed (2026-11-25) |
| Terms | `https://web.cinepax.com/api/cms/pages/terms` (sha256 `62dc051d…46a2d56`, 2026-11-25). Ticket sales, patron conduct, Lahore jurisdiction. No clause on automated access, bots or copying found (audit 2026-11-23; owner re-read 2026-11-25: no such clause). |
| Verdict | **Allowed** |
| Technical verdict | **Go** (pending the P0-09 runner probe) |
| Effort | S |

## Branches

| id | Branch | City | `[lng, lat]` | Notes |
|---|---|---|---|---|
| `cinepax-packages-mall` | `0000000014` | Lahore | `[74.35692149646812, 31.47168923714777]` | |
| `cinepax-world-trade-center` | `0000000011` | Islamabad | `[73.15827985420117, 33.5215501394146]` | Giga Mall, GT Road |
| `cinepax-ocean-mall` | `0000000002` | Karachi | `[67.03598697114558, 24.82401989059472]` | City confirmed by map coordinates (audit had inferred it) |

## Adapter notes

- Use the session's **calendar** date and time for `startsAt` (PKT → UTC), not `businessDate`; `lateNight` sessions fall after midnight.
- One `/api/movies` request per branch per run; `/api/cinemas` once per run.

## Runner reachability (P0-09)

Not run yet.
