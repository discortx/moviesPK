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
| Technical verdict | **Go** (runner probe passed 2026-11-25) |
| Effort | S |

## Branches

| id | Branch | City | `[lng, lat]` | Notes |
|---|---|---|---|---|
| `cinepax-packages-mall` | `0000000014` | Lahore | `[74.35692149646812, 31.47168923714777]` | |
| `cinepax-world-trade-center` | `0000000011` | Islamabad | `[73.15827985420117, 33.5215501394146]` | Giga Mall, GT Road |
| `cinepax-ocean-mall` | `0000000002` | Karachi | `[67.03598697114558, 24.82401989059472]` | City confirmed by map coordinates (audit had inferred it) |

## Adapter notes

Implemented in `scraper/src/moviespk_scraper/adapters/cinepax.py` (P1-06, 2026-11-25):

- **One request per branch per run:** `GET /api/movies?cinemaId=<branch>`; movies and showtimes are both read from it. `/api/cinemas` is not needed.
- **Late shows:** Cinepax files a show after midnight under the previous `businessDate` with `lateNight: true`. The start is `calendarDate` + the clock time of `showtime` (PKT → UTC in the normalizer). Fixture case: Ocean Mall, *Resident Evil*, 00:15 listed under 27 Nov → starts 2026-11-28 00:15 PKT. A `showtime` whose date disagrees with `calendarDate` is treated as drift.
- **Fields used:** film `id` (local key), `title`, `duration`, `genre`, `rating`, `description`, `releaseDate`; session `sessionId`, `showtime`, `calendarDate`, `screenName`, screen `type` (format), `seatsAvailable`. Posters, backdrops and cast are ignored (cinema artwork is never mirrored).
- **Drift:** a non-200 answer, non-JSON, a non-list, a film or session missing a required key, or a film from another branch → `SchemaDriftError`; the cleaned payload is saved to `debug/`.
- **Booking link:** `booking_url_template` supports `{branch}`, `{sessionId}`, `{filmId}`. The real Cinepax booking URL pattern is still to be confirmed (one click on a showtime); until then no `bookingUrl` is set.

## Runner reachability (P0-09)

2026-11-25T13:19Z, GitHub-hosted `ubuntu-latest`, real User-Agent, one GET per venue after robots.txt:

| Venue | robots.txt | Main GET | Bytes | Challenge page | Result |
|---|---|---|---|---|---|
| `cinepax-packages-mall` (`/api/movies?cinemaId=0000000014`) | 404 | 200 | 10561 | no | reachable |
| `cinepax-world-trade-center` (`…=0000000011`) | 404 | 200 | 6961 | no | reachable |
| `cinepax-ocean-mall` (`…=0000000002`) | 404 | 200 | 15312 | no | reachable |
