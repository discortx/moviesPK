import { z } from "zod";
import { CITIES } from "./cities.js";
import { addDays, isIsoDate, pktDate } from "./dates.js";

/** Query parameters shared by the endpoints (plan §9.1). All schemas are strict. */

export const MAX_DAYS_AHEAD = 7;

const citySlugs = CITIES.map((c) => c.slug) as [string, ...string[]];
export const CityParam = z.enum(citySlugs);

/**
 * `date`: `YYYY-MM-DD` PKT, from today to today + 7 (inclusive); defaults to today.
 * Evaluated per request, so "today" is always the current PKT date.
 */
export function dateParam(now: () => Date = () => new Date()) {
  return z
    .string()
    .refine(isIsoDate, "date must be YYYY-MM-DD")
    .optional()
    .transform((value, ctx) => {
      const today = pktDate(now());
      const date = value ?? today;
      if (date < today || date > addDays(today, MAX_DAYS_AHEAD)) {
        ctx.addIssue({
          code: "custom",
          message: `date must be between ${today} and ${addDays(today, MAX_DAYS_AHEAD)} (PKT)`,
        });
        return z.NEVER;
      }
      return date;
    });
}
