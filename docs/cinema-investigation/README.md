# Cinema investigation (P0-08)

One document per adapter group. The desk audit is in [cinema-viability-audit.md](../cinema-viability-audit.md); these documents record the evidence for the venues being enabled. Config: [`scraper/config/cinemas.yml`](../../scraper/config/cinemas.yml) (each venue enabled once its adapter passed a clean live dry run, P2-01).

## Status

| Order | Venue | City | Adapter | Evidence | Coordinates | Terms re-read | Runner probe (P0-09) | Scope (P2-07) |
|---|---|---|---|---|---|---|---|---|
| 1 | Cinepax Packages Mall | Lahore | A [cinepax](cinepax.md) | 2026-11-25 | yes | done | reachable (2026-11-25) | Enabled (2026-11-28) |
| 2 | Cinepax World Trade Center | Islamabad | A | 2026-11-25 | yes | done | reachable (2026-11-25) | Enabled (2026-11-28) |
| 3 | Cinepax Ocean Mall | Karachi | A | 2026-11-25 | yes | done | reachable (2026-11-25) | Enabled (2026-11-28) |
| 4 | Universal Cinemas Emporium Mall | Lahore | B [vista](vista.md) | 2026-11-25 | yes | done | reachable (2026-11-25) | Enabled (2026-11-28) |
| 5 | CineStar Township | Lahore | B | 2026-11-25 | yes | done | reachable (2026-11-25) | Enabled (2026-11-28) |

**First adapter:** A (Cinepax JSON): three venues, three cities, simplest source.

**Enabled (scraped hourly):** Cinepax Packages Mall (P1-13); Cinepax World Trade Center, Cinepax Ocean Mall, Universal Cinemas Emporium Mall and CineStar Township (P2-01, 2026-11-28). All five are enabled.

**Scope (P2-07, 2026-11-28):** every venue is Enabled or Dropped with a recorded reason. None is Dropped: none has been blocked. A venue still blocked after 3 polite runs is dropped (runbook "Blocked site"); never a proxy, VPS or IP rotation.

**Reachable count: 5 of 5** (P0-09, 2026-11-25). Minimum of 5 met → G0 cinema criterion satisfied.
