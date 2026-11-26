/**
 * PKT date helpers (plan §9.1 "PKT date grouping").
 *
 * Pakistan Standard Time is UTC+05:00 with no daylight saving, so a fixed offset is exact.
 * `date=D` selects showtimes with `D 00:00 PKT <= startsAt < D+1 00:00 PKT`, which is the
 * UTC range `[D-1 19:00Z, D 19:00Z)`.
 */

export const PKT_OFFSET_MS = 5 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** The PKT calendar date of an instant, as `YYYY-MM-DD`. */
export function pktDate(instant: Date): string {
  return new Date(instant.getTime() + PKT_OFFSET_MS).toISOString().slice(0, 10);
}

/** Whether `value` is a real calendar date written as `YYYY-MM-DD`. */
export function isIsoDate(value: string): boolean {
  const m = ISO_DATE.exec(value);
  if (!m) return false;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return d.toISOString().slice(0, 10) === value;
}

/** `YYYY-MM-DD` plus `days` calendar days. */
export function addDays(date: string, days: number): string {
  if (!isIsoDate(date)) throw new RangeError(`not a date: ${date}`);
  return new Date(Date.parse(`${date}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

/** UTC bounds of PKT day `date`: `[start, end)`. */
export function pktDayRange(date: string): { start: Date; end: Date } {
  if (!isIsoDate(date)) throw new RangeError(`not a date: ${date}`);
  const start = new Date(Date.parse(`${date}T00:00:00Z`) - PKT_OFFSET_MS);
  return { start, end: new Date(start.getTime() + DAY_MS) };
}
