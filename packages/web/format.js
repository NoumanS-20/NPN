/**
 * Formatting helpers.
 *
 * One place for every number that reaches a screen, so a quantity looks the same
 * on the supplier table as it does on the allocation panel. Every formatter
 * survives null and undefined, because the data genuinely has gaps — a supplier
 * with no trading history has no on-time rate, and showing "0%" there would be a
 * lie.
 */

const MISSING = "—";

/**
 * Money, no decimals — these businesses deal in whole currency units.
 *
 * The second argument is guarded because these formatters are handed straight
 * to the table, which calls them as `format(value, row)`. Passing `money` by
 * name then put a row object into the currency slot and threw "Invalid currency
 * code" across three screens. A formatter has to survive its own calling
 * convention.
 */
export function money(value, currency) {
  if (value == null || Number.isNaN(value)) return MISSING;
  const code = typeof currency === "string" ? currency : "USD";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: code,
    maximumFractionDigits: 0,
  }).format(value);
}

/** Unit price, where fractions of a cent matter. */
export function price(value) {
  if (value == null || Number.isNaN(value)) return MISSING;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(value);
}

export function units(value) {
  if (value == null || Number.isNaN(value)) return MISSING;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

/** A rate held as 0–1, shown as a percentage. */
export function pct(value, digits = 1) {
  if (value == null || Number.isNaN(value)) return MISSING;
  const places = Number.isInteger(digits) ? digits : 1;
  return `${(value * 100).toFixed(places)}%`;
}

/** A change already expressed in percent, with its sign kept. */
export function delta(value, digits = 1) {
  if (value == null || Number.isNaN(value)) return MISSING;
  const places = Number.isInteger(digits) ? digits : 1;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(places)}%`;
}

export function days(value) {
  if (value == null || Number.isNaN(value)) return MISSING;
  return `${Math.round(value)} d`;
}

export function weeks(value) {
  if (value == null || Number.isNaN(value)) return MISSING;
  return `wk ${value}`;
}

export function seconds(value) {
  if (value == null || Number.isNaN(value)) return MISSING;
  return `${value.toFixed(2)}s`;
}

/**
 * Which band a probability falls into.
 *
 * The thresholds match the optimiser's: 25% is where an order is worth a second
 * look, 40% is where it should be held. Keeping them identical means the colour
 * on screen and the decision in the model always agree.
 */
export function riskBand(probability) {
  if (probability == null || Number.isNaN(probability)) return "low";
  if (probability >= 0.4) return "high";
  if (probability >= 0.25) return "medium";
  return "low";
}

/** Shorten a long material or supplier name for a dense table. */
export function truncate(text, limit = 42) {
  if (!text) return MISSING;
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

/** Title-case an identifier such as "cheapest_first". */
export function humanise(key) {
  if (!key) return MISSING;
  const spaced = String(key).replace(/[_-]+/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
