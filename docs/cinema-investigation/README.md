# Cinema investigation (P0-08)

One document per adapter group. The desk audit is in [cinema-viability-audit.md](../cinema-viability-audit.md); these documents record the evidence for the venues being enabled. Config: [`scraper/config/cinemas.yml`](../../scraper/config/cinemas.yml) (all `enabled: false` until their adapter exists, P2-01).

## Status

| Order | Venue | City | Adapter | Evidence | Coordinates | Terms re-read | Runner probe (P0-09) |
|---|---|---|---|---|---|---|---|
| 1 | Cinepax Packages Mall | Lahore | A [cinepax](cinepax.md) | 2026-11-25 | yes | done | reachable (2026-11-25) |
| 2 | Cinepax World Trade Center | Islamabad | A | 2026-11-25 | yes | done | reachable (2026-11-25) |
| 3 | Cinepax Ocean Mall | Karachi | A | 2026-11-25 | yes | done | reachable (2026-11-25) |
| 4 | Universal Cinemas Emporium Mall | Lahore | B [vista](vista.md) | 2026-11-25 | yes | done | reachable (2026-11-25) |
| 5 | CineStar Township | Lahore | B | 2026-11-25 | yes | done | reachable (2026-11-25) |

**First adapter:** A (Cinepax JSON): three venues, three cities, simplest source.

**Reachable count: 5 of 5** (P0-09, 2026-11-25). Minimum of 5 met → G0 cinema criterion satisfied.
