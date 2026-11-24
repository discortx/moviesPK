# ADR-0001: Respect robots.txt when scraping cinema sites

- **Status:** Accepted
- **Date:** 2026-11-22
- **Supersedes:** ADR-11 in `architecture.md` §3 ("Scraping etiquette/legal: ignore robots.txt everywhere, public repo")
- **Numbering note:** this file belongs to the repository's own ADR series (`docs/adr/NNNN-*.md`). The `ADR-01` to `ADR-17` entries in `architecture.md` are a separate numbering. `architecture.md` is not edited by this ADR. The spots that must change later are listed in `plan.md`, section "Required amendments to architecture.md".

## Context

ADR-11 chose to ignore robots.txt on every target site, with a public repository. The project owner has since checked the candidate cinema websites. Most have a robots.txt that allows scraping, and their terms of service do not prohibit it. A few are unclear or disallow it.

Because most sites allow automated access, ignoring robots.txt is no longer needed for most of the scope. It would also remove the strongest evidence of good faith if a dispute arose. The owner therefore wants a policy that follows each site's published rules.

## Decision

1. **Respect robots.txt.** The scraper reads each site's robots.txt and refuses to request any path it disallows for the scraper's User-Agent. In `scraper/config/cinemas.yml` the default is `robots_policy: respect`.
2. **Check specific endpoints, not only the site root.** The investigation (Phase 0) records the robots.txt result for the exact paths an adapter will call, including any seat-status endpoint.
3. **Record evidence per cinema.** Date checked, robots.txt result per endpoint, terms-of-service link, a short note of what the terms say, and a saved hash or dated copy of the robots.txt and terms text. The verdict is Allowed, Unclear or Disallowed.
4. **Unclear or Disallowed cinemas are never scraped silently.** Each one is handled by exactly one of: (a) excluded from the list; (b) the owner approaches the cinema for permission or a feed (config value `permission_granted` plus a reference to the written permission); (c) counsel gives a written view. The decision is recorded per cinema.
5. **`robots_policy: ignore` is not accepted.** Config validation rejects it. Reintroducing it needs a new ADR.
6. **Politeness controls stay:** descriptive User-Agent with a contact URL, `min_delay_ms`, `max_concurrency=1` per site, jitter, exponential backoff honoring `Retry-After`, per-site circuit breaker. So do the `/takedown` page and the per-cinema `enabled: false` kill switch.
7. **Ongoing monitoring.** The daily canary re-checks robots.txt and the terms hash for every enabled cinema. It alerts when a previously allowed path becomes disallowed or the terms text changes. A newly disallowed path is refused by the HTTP client (run status `blocked`, error type `RobotsDisallowedError`).
8. *(Amended 2026-11-23. MoviesPK is personal and non-commercial, and the owner proceeds on that basis. A formal legal review is not required for implementation or launch; see `plan.md` OD5 and OD8. Items 1–7 and 9 are unchanged. The original text is kept below for history.)* ~~**Legal review stays, but lighter and earlier.** A short consult with Pakistani counsel happens in Phase 0 or early Phase 1 (copyright of posters and synopses; rules on automated access). It is no longer a hard blocker at the end. A written counsel outcome is still required before any public announcement.~~
9. **Fixtures and debug artifacts** (risks N1 and N2) must never include content from a robots-disallowed path.

## Consequences

- **Lower legal and blocking exposure.** The risk R1 likelihood drops. It is not removed: terms and copyright questions remain, and counsel is still consulted.
- **The cinema list may shrink.** Cinemas whose verdict is Unclear or Disallowed are excluded unless permission is obtained. The 10+ cinemas goal (architecture ADR-01) may not be met, so the plan adds a Phase 0 go/no-go gate and a minimum viable launch option (5 cinemas in Lahore and Karachi).
- **Seat status becomes optional per cinema.** Seat requests are one per show and most likely to be disallowed. A cinema may ship with showtimes only, seats `unknown`.
- **New work:** a robots check in the HTTP client, evidence capture in Phase 0, a robots and terms re-check in the canary, and per-cinema decision records.
- **A robots change can switch an adapter off.** This is handled as a `blocked` alert, not as silent failure.
- **Public repo is unchanged.** It stays public (architecture ADR-15). Evidence files hold hashes and short summaries, not full copies of third-party pages where avoidable.
- **This is not legal advice.**
