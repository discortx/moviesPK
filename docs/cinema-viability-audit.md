# MoviesPK: Cinema Viability Audit (GO/NO-GO)

- **Date of evidence:** 2026-11-23. All official sites were fetched over HTTP on this date. No login, no CAPTCHA solving, no cookies beyond a site's own anonymous session.
- **Method:**
  - Fetched the homepage, `robots.txt`, the showtimes page or its underlying JSON/XHR endpoint, and the terms page for each operator. Recorded what was actually returned.
  - Spot-checks were repeated independently for Cinepax (robots 404; `/api/cinemas`; `/api/movies?cinemaId=0000000014` returned sessions dated 2026-11-23 and 2026-11-24), Universal Emporium (sessions 23–27 Nov), CineStar Township (sessions 23–26 Nov), The Arena (robots `Allow: /`; `/api/get_schedules` returned a schedule), and the robots.txt responses of all seven main operators.
- **Policy applied:**
  - robots.txt is respected (ADR-0001, architecture ADR-11).
  - Listings in third-party directories or aggregators are **not** counted and are **not** treated as permission to scrape.
  - A venue counts only if current, dated showtimes were observed on the cinema's **own** website.
- **Not legal advice.** Terms-of-service notes are summaries of what was found, not a legal reading.
- **Scope of the decision.** MoviesPK is personal and non-commercial (owner-confirmed 2026-11-23). This GO/NO-GO is a technical and practical viability decision; formal legal assessment is not a condition. robots.txt compliance and the per-cinema kill switch are mandatory.

## 1. Classification rules

| Class | Rule |
|---|---|
| **VERIFIED VIABLE** | All of the following:<br>- the venue is listed on the operator's official site;<br>- current dated showtimes were observed there without login;<br>- robots.txt does not disallow the paths needed (a 4xx robots.txt means "allow all" under RFC 9309);<br>- no terms clause found that prohibits automated access or copying;<br>- the location is stated or reasonably identifiable from the official site. |
| **CONDITIONALLY VIABLE** | Most criteria are met, but one item needs owner or manual action, for example ambiguous terms, an address not on the official site, or undated showtimes. |
| **EXCLUDED** | Closed, no online showtimes, domain lost, robots disallows the paths, or login is required. |
| **NEEDS MANUAL REVIEW** | No official site could be found or fetched, so nothing could be verified. |

"Verified" here means desk-verified on 2026-11-23. **Reachability from GitHub Actions runners has not been tested yet** (plan task P0-09). It is the remaining gate before an adapter is enabled.

## 2. Venue table

Each venue is one physical cinema, counted separately. "Group" is the shared adapter.

| # | Cinema | City | Official URL | Data source | Showtimes verified | Robots status | Complexity | Decision |
|---|---|---|---|---|---|---|---|---|
| 1 | Cinepax Packages Mall | Lahore | https://web.cinepax.com (`/api/movies?cinemaId=0000000014`) | JSON (public GET API) | Yes, 23–24 Nov (independently re-checked) | No robots.txt (404) → allowed | Low (group A) | **VERIFIED VIABLE** |
| 2 | Cinepax Amanah Mall | Lahore (*inferred from 042 phone code; site says "Amanah Mall"*) | web.cinepax.com (`cinemaId=0000000012`) | JSON | Yes, 23–24 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** (confirm city when entering coordinates) |
| 3 | Cinepax Ocean Mall | Karachi (*inferred; site says "Ocean Tower"*) | web.cinepax.com (`0000000002`) | JSON | Yes, 23–24 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** (confirm city) |
| 4 | Cinepax World Trade Center (Giga Mall) | Islamabad | web.cinepax.com (`0000000011`) | JSON | Yes, 23–25 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** |
| 5 | Cinepax Jinnah Park | Rawalpindi (*inferred from 051 phone code and "Kechari Road"*) | web.cinepax.com (`0000000003`) | JSON | Yes, 23–25 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** (confirm city) |
| 6 | Cinepax HotelOne | Faisalabad | web.cinepax.com (`0000000004`) | JSON | Yes, 23–24 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** |
| 7 | Cinepax Boulevard Mall | Hyderabad | web.cinepax.com (`0000000010`) | JSON | Yes, 23–24 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** |
| 8 | Cinepax Mall of Sialkot | Sialkot | web.cinepax.com (`0000000013`) | JSON | Yes, 23–24 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** |
| 9 | Cinepax Nayyar Mall | Gujrat | web.cinepax.com (`0000000009`) | JSON | Yes, 23–25 Nov | 404 → allowed | Low (A) | **VERIFIED VIABLE** |
| 10 | Cinepax Kings Mall | **Not stated** (address says only "Punjab") | web.cinepax.com (`0000000006`) | JSON | Yes, 23–24 Nov | 404 → allowed | Low (A) | **CONDITIONALLY VIABLE**: location must be confirmed before publication |
| 11 | Universal Cinemas, Emporium Mall | Lahore (Abdul Haque Rd) | https://universalcinemas.com/browsing/Cinemas/Details/8888 | Static HTML (Vista; `<time datetime>`) | Yes, 23–27 Nov (re-checked) | No valid robots.txt: `/robots.txt` redirects to an HTML error page (HTTP 200, no rules) → no restrictions | Low–Med (B) | **VERIFIED VIABLE** |
| 12 | Universal Cinemas, The Grand Mall | Multan (Noor Blvd) | …/browsing/Cinemas/Details/9999 | Static HTML (Vista) | Yes, 23–26 Nov | As #11 | Low–Med (B) | **VERIFIED VIABLE** |
| 13 | CineStar Township | Lahore (Ali Rd, Township) | https://cinestar.pk/browsing/Cinemas/Details/0005 | Static HTML (Vista) | Yes, 23–26 Nov (re-checked) | No valid robots.txt (redirect to an HTML error page) → no restrictions | Low–Med (B) | **VERIFIED VIABLE** |
| 14 | CineStar Xinhua Mall | Lahore (Gulberg III) | …/Details/0001 | Static HTML (Vista) | Yes, 23–26 Nov | As #13 | Low–Med (B) | **VERIFIED VIABLE** |
| 15 | CineStar DHA Raya | Lahore (DHA Phase 6) | …/Details/0002 | Static HTML (Vista) | Yes, 23–26 Nov | As #13 | Low–Med (B) | **VERIFIED VIABLE** |
| 16 | CineStar Xin Mall | Sargodha (Queen Road) | …/Details/0000000006 | Static HTML (Vista) | Yes, 23–26 Nov | As #13 | Low–Med (B) | **VERIFIED VIABLE** |
| 17 | Cue Cinemas Gulberg III | Lahore (57 Main Blvd) | https://cuecinemas.com/Browsing/Cinemas/Details/1001 | Static HTML (Vista) | Yes, 23–29 Nov (7 days) | 404 → allowed | Low–Med (B) | **CONDITIONALLY VIABLE**: terms say services are "to be employed solely for their designated purposes and in the prescribed Manner". Treated as **Unclear** under ADR-0001 until reviewed or permission obtained. |
| 18 | The Arena, Bahria Town | Islamabad | https://thearena.com.pk (`POST /api/get_schedules`, branchId=1) | JSON wrapping an HTML fragment | Yes, 23–26 Nov (re-checked for 24 Nov) | `User-agent: * / Allow: /` | Med (C) | **VERIFIED VIABLE** (no terms page found) |
| 19 | The Arena, Bahria Orchard | Lahore | branchId=2 | JSON + HTML fragment | Yes, 23–26 Nov | Allow: / | Med (C) | **VERIFIED VIABLE** |
| 20 | The Arena, Bahria Town Tower | Karachi (Tariq Rd) | branchId=3 | JSON + HTML fragment | Yes, 23–26 Nov | Allow: / | Med (C) | **VERIFIED VIABLE** |
| 21 | CineGold Plex, Bahria Town | Islamabad | https://cinegoldplex.com (`POST /api/get_schedules`, branch 2) | JSON + HTML fragment (same platform as The Arena) | Yes, 23–26 Nov | Apex 404; `www` robots has only content-signal comments, no rules → allowed | Med (C) | **VERIFIED VIABLE** (no terms page found) |
| 22 | CineGold Plex, Bahria Town | Lahore | branch 1 | As above | Yes, 23–26 Nov | As above | Med (C) | **VERIFIED VIABLE** |
| 23 | CineGold Plex, Bahria Town | Karachi (Super Highway) | branch 3 | As above | Yes, 23–26 Nov | As above | Med (C) | **VERIFIED VIABLE** |
| 24 | Nueplex DHA | Karachi (*site meta keywords only; no address on the official site*) | https://nueplex.com (`POST /branch` then `POST /showtime.html`) | Server-rendered HTML; needs an anonymous session cookie | Yes, 23 Nov; date list 23–26 Nov | 404 → allowed | Med (D, stateful) | **CONDITIONALLY VIABLE**: the address is not on the official site |
| 25 | Nueplex Askari IV | Karachi (*same basis*) | as above, branch=2 | As above | Yes, 23 Nov | 404 → allowed | Med (D) | **CONDITIONALLY VIABLE**: as #24 |
| 26 | JFC Cineplex | Islamabad (*third-party source only*) | https://jfccineplex.com | Static HTML (WordPress) | **Weekday names only, no dates** | Only `/wp-admin/` disallowed → allowed | Med (date inference) (E) | **CONDITIONALLY VIABLE**: undated showtimes and an unconfirmed location |
| 27 | Atrium Cinemas | Karachi | atriumcinemas.com.pk | — | No: the domain now serves a crypto casino | n/a | — | **EXCLUDED** (no official showtimes; domain lost) |
| 28 | Capri Cinema | Karachi | capricinema.com.pk | — | No: empty "Index of /" | n/a | — | **EXCLUDED** (no online showtimes) |
| 29 | Centaurus Cineplex | Islamabad | thecentaurusmall.com/services/cineplex/ (mall page) | — | No showtimes on any official page; centauruscineplex.com unreachable | Allowed | — | **EXCLUDED** (no online showtimes) |
| 30 | Super Cinema; Prince; Lyric; Nishat; Mall of Lahore; Mega Multiplex | — | No official site found or reachable | — | Not fetchable | Unreachable | — | **NEEDS MANUAL REVIEW** |

**Not counted:** the old CineStar domain `cinestar.com.pk` now redirects to a gambling site. Configure only `cinestar.pk`.

## 3. Per-operator answers to the 14 investigation questions

| Question | Cinepax (A) | Universal / CineStar / Cue (B, Vista) | The Arena / CineGold Plex (C) | Nueplex (D) | JFC (E) |
|---|---|---|---|---|---|
| 1. Operating? | Yes: 10 branches listed, current sessions | Yes | Yes | Yes (2 branches) | Current films listed; a third-party report mentions closures (unconfirmed) |
| 2. Official site | web.cinepax.com | universalcinemas.com, cinestar.pk, cuecinemas.com | thearena.com.pk, cinegoldplex.com | nueplex.com | jfccineplex.com |
| 3. Current movies? | Yes | Yes | Yes | Yes | Yes |
| 4. Showtimes public? | Yes | Yes | Yes | Yes | Weekday times only |
| 5. Without login? | Yes | Yes | Yes | Yes (anonymous session cookie only) | Yes |
| 6. Next 3–7 days? | **2–3 days** (23–24/25 Nov) | 4–5 days; Cue 7 | 4 days (27–28 Nov empty) | 4 days in the date list | No dates |
| 7. JSON/XHR? | Yes: `GET /api/cinemas`, `/api/movies?cinemaId=` | No | Yes: `POST /api/get_schedules` (HTML in JSON) | No (POST returns HTML) | No |
| 8. Static HTML? | n/a | Yes (`<time datetime>`) | Fragment | Yes | Yes |
| 9. Browser automation needed? | No | No | No | No | No |
| 10. robots.txt | 404 (allow) | Redirect to an HTML error page (no rules); Cue 404 | Arena `Allow: /`; CineGold 404 or no rules | 404 | Only `/wp-admin/` disallowed |
| 11. Terms of service | `/api/cms/pages/terms` (updated July 2026): tickets, conduct, Lahore jurisdiction. No clause on automated access found. | Ticketing terms. Nothing on automated access. Cue has a "designated purposes … prescribed Manner" clause, which is ambiguous. | No terms page found (`/terms` 404); privacy policy only | Ticket/patron terms only | None found |
| 12. Booking link | Yes (on-site) | Yes (`visSelectTickets.aspx?cinemacode=&txtSessionId=`) | Arena: app only. CineGold: external booking with login. | No web booking found | "Online Booking" behind login |
| 13. Adapter complexity | Low | Low–Med | Med (POST; per-lounge calls for CineGold) | Med (stateful cookie per branch) | Med (date inference) |
| 14. Shared adapter? | 1 adapter, 10 venues | 1 Vista adapter, 7 venues | 1 adapter, 6 venues (optional `loungeId`) | 1 adapter, 2 venues | Own adapter |

Notes for adapters:
- **POST endpoints:** robots.txt rules match URL paths, not HTTP methods. None of the robots files disallow `/api/get_schedules`, `/branch` or `/showtime.html`. Treating them as allowed is an interpretation, recorded here.
- **Late-night shows:** Cinepax has separate `businessDate` and `calendarDate` fields and a `lateNight` flag. Nueplex marks after-midnight shows with the next date. Always use the **calendar** date and time for `startsAt` (PKT → UTC).
- **Seats:** the Cinepax session JSON includes `seatsAvailable`. That makes Cinepax a candidate for optional seat status, subject to `plan.md` §10.6.
- **Short windows:** most operators publish only 2–5 days ahead. Assumption A4 (3–7 days) is only **partly true**. The UI must not imply a full week of coverage.
- **Domain takeover risk:** two former cinema domains now serve gambling sites. The canary must check expected page structure, so that a hijacked domain shows up as drift and is never published.

## 4. Counts

| Measure | Count |
|---|---|
| Venues evaluated individually (excluding the "manual review" group) | 29 |
| **VERIFIED VIABLE venues** | **21**: Cinepax 9, Universal 2, CineStar 4, The Arena 3, CineGold Plex 3 |
| CONDITIONALLY VIABLE venues | 5: Cinepax Kings Mall, Nueplex ×2, Cue Gulberg, JFC |
| EXCLUDED venues | 3: Atrium, Capri, Centaurus |
| NEEDS MANUAL REVIEW | 6 names with no official site found |
| Independent adapters for the 21 verified venues | **3**: Cinepax JSON (A), Vista HTML (B), Arena/CineGold platform (C) |
| Adapters if all conditional venues are added | 5 (adds Nueplex D and JFC E; Cue reuses B) |

**Concentration check.** The rule counts venues, not operators. Even so:
- without the 9 Cinepax venues, 12 verified venues remain on 2 adapters;
- without the Vista group, 15 remain.

The five-venue minimum therefore does not depend on any single operator.

## 5. Decision

**21 VERIFIED VIABLE venues ≥ 5 → GO.** The minimum of five is not lowered.

The GO covers desk viability only. Each venue still needs, before it is enabled:
- the GitHub-runner reachability probe (P0-09);
- map-checked coordinates;
- a robots/terms evidence snapshot.

A venue that fails the runner probe drops out of the count. The canary re-checks robots.txt and the terms daily.

## 6. Recommended first five venues

Two adapters, three cities, plus a fourth city through Cinepax WTC:

| Order | Venue | City | Adapter | Why |
|---|---|---|---|---|
| 1 | Cinepax Packages Mall | Lahore | A (Cinepax JSON) | Cleanest source (public JSON, no robots restrictions); city on the site; booking link |
| 2 | Cinepax World Trade Center | Islamabad | A | Same adapter; second city; window of 3 days |
| 3 | Cinepax Ocean Mall | Karachi (confirm) | A | Same adapter; third city (confirm the address when entering coordinates) |
| 4 | Universal Cinemas, Emporium Mall | Lahore | B (Vista HTML) | Second, independent adapter, so the launch does not rely on one operator; 4–5 day window |
| 5 | CineStar Township | Lahore | B | Reuses the Vista adapter; a different operator from Universal |

Alternative for #3, if the Ocean Mall city is not confirmed: Cinepax HotelOne (Faisalabad, city stated on the site). Next additions are The Arena and CineGold Plex (adapter C), which add Karachi, Lahore and Islamabad venues.

## 7. Evidence URLs (fetched 2026-11-23; source type: official cinema website unless marked)

- **Cinepax:**
  - https://web.cinepax.com/
  - https://web.cinepax.com/robots.txt (404)
  - https://web.cinepax.com/api/cinemas
  - https://web.cinepax.com/api/movies?cinemaId=0000000014 (and IDs 02, 03, 04, 06, 09, 10, 11, 12, 13)
  - https://web.cinepax.com/api/cms/pages/terms
- **Universal:**
  - https://universalcinemas.com/browsing/Cinemas
  - …/Details/8888, …/Details/9999
  - https://universalcinemas.com/browsing/General/TermsAndConditions
  - https://universalcinemas.com/robots.txt (redirects to `/Browsing/General/Error`)
- **CineStar:**
  - https://cinestar.pk/browsing/Cinemas
  - …/Details/0001, 0002, 0005, 0000000006
  - https://cinestar.pk/browsing/General/TermsAndConditions
  - https://cinestar.pk/robots.txt (redirects to the error page)
- **Cue:**
  - https://cuecinemas.com/Browsing/Cinemas/Details/1001
  - https://cuecinemas.com/Browsing/General/TermsAndConditions
  - https://cuecinemas.com/robots.txt (404)
- **The Arena:**
  - https://thearena.com.pk/robots.txt
  - https://thearena.com.pk/weekly_schedule
  - POST https://thearena.com.pk/api/get_schedules
  - https://thearena.com.pk/contact-us
  - /terms (404)
- **CineGold Plex:**
  - https://cinegoldplex.com/showtimes
  - POST https://cinegoldplex.com/api/get_schedules
  - https://cinegoldplex.com/contact
  - robots.txt (404) and https://www.cinegoldplex.com/robots.txt
- **Nueplex:**
  - https://nueplex.com/
  - POST /branch
  - POST /showtime.html
  - https://www.nueplex.com/termsandconditions.html
  - robots.txt (404)
- **JFC Cineplex:**
  - https://jfccineplex.com/
  - https://jfccineplex.com/robots.txt
  - /show-times/ (empty)
- **Excluded:**
  - https://atriumcinemas.com.pk/ (casino)
  - https://capricinema.com.pk/ (empty index)
  - https://thecentaurusmall.com/services/cineplex/
- **Third-party evidence, used only for context and not counted:**
  - Wikipedia and locatecinemas.com (CineStar)
  - graana.com and zameen.com (Centaurus, JFC)
  - tribune.com.pk (Super Cinema, JFC closures)
  - thefridaytimes.com (Capri)

**Confidence:**
- High for the Cinepax, Universal, CineStar and Arena rows (independently re-checked).
- Medium for the other rows (single fetch).
- Showtime availability is a snapshot from one day. Re-check it within 7 days of implementation (P0-08).
