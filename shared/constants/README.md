# shared/constants

Vocabularies shared by the scraper (Pydantic), the API (Zod) and the web. Both language
models are written by hand; contract tests assert they equal these lists (plan §13).

- Genres and languages: an unmapped source value becomes `other` (plan §10.3 step 2 calls
  this `OTHER`; lower case is used here for consistency with the other slug vocabularies).
  Formats keep the upper-case `OTHER` exactly as in plan §8.1.
- `cities.json` is **generated** from `scraper/config/cities.yml` by
  `scripts/gen_constants.py`. Do not edit it by hand; CI fails if it is stale.
