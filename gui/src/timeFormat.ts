/** Display rounding only. Never use a formatted label as a history cursor. */
export type FormattedTime = {label: string; exact: string; rounded: boolean; valid: boolean};
type Ratio = {numerator: bigint; denominator: bigint};

const MAX_TEXT = 20000;
const MAX_EXPONENT = 10000;
const power = (exponent: number) => 10n ** BigInt(exponent);

function parseTime(text: string): Ratio | undefined {
  if (!text || text.length > MAX_TEXT) return;
  const fraction = /^([+-]?\d+)\/(\d+)$/.exec(text);
  if (fraction) {
    const numerator = BigInt(fraction[1]), denominator = BigInt(fraction[2]);
    if (numerator < 0n || denominator === 0n) return;
    return {numerator, denominator};
  }
  const decimal = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(text);
  if (!decimal) return;
  const fractionDigits = decimal[3] ?? decimal[4] ?? '';
  const exponent = Number(decimal[5] || 0) - fractionDigits.length;
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > MAX_EXPONENT) return;
  let numerator = BigInt((decimal[2] || '0') + fractionDigits);
  if (decimal[1] === '-' && numerator !== 0n) return;
  let denominator = 1n;
  if (exponent < 0) denominator = power(-exponent);
  else numerator *= power(exponent);
  return {numerator, denominator};
}

function decimalExponent(numerator: bigint, denominator: bigint): number {
  let exponent = numerator.toString().length - denominator.toString().length;
  if (exponent >= 0 ? numerator < denominator * power(exponent)
    : numerator * power(-exponent) < denominator) exponent--;
  return exponent;
}

function quantize(numerator: bigint, denominator: bigint, places: number) {
  if (places >= 0) numerator *= power(places);
  else denominator *= power(-places);
  const integer = (2n * numerator + denominator) / (2n * denominator);
  return {integer, rounded: integer * denominator !== numerator};
}

function fixedDecimal(integer: bigint, places: number): string {
  if (places <= 0) return (integer * power(-places)).toString();
  const digits = integer.toString().padStart(places + 1, '0');
  const fraction = digits.slice(-places).replace(/0+$/, '');
  return digits.slice(0, -places) + (fraction ? '.' + fraction : '');
}

function scientific(integer: bigint, exponent: number): string {
  const digits = integer.toString();
  const rest = digits.slice(1).replace(/0+$/, '');
  return digits[0] + (rest ? '.' + rest : '') + 'e' + exponent;
}

export function formatTime(value: unknown): FormattedTime {
  const exact = typeof value === 'string' || typeof value === 'number' || typeof value === 'bigint'
    ? String(value) : '';
  const unavailable: FormattedTime = {label: 'Time unavailable', exact, rounded: false, valid: false};
  try {
    const ratio = parseTime(exact.trim());
    if (!ratio) return unavailable;
    const {numerator: n, denominator: d} = ratio;
    if (n === 0n) return {label: '0', exact, rounded: false, valid: true};
    let label: string, rounded: boolean;
    if (n * 1000n >= d && n < d * 1000000000n) {
      const result = quantize(n, d, 3);
      rounded = result.rounded;
      label = result.integer === 1000000000000n ? '1e9' : fixedDecimal(result.integer, 3);
    } else {
      let exponent = decimalExponent(n, d);
      const result = quantize(n, d, 5 - exponent);
      let integer = result.integer;
      rounded = result.rounded;
      if (integer === 1000000n) {integer = 100000n; exponent++;}
      // A six-significant-digit carry can enter the ordinary display range.
      label = exponent >= -3 && exponent < 9
        ? fixedDecimal(integer, 5 - exponent) : scientific(integer, exponent);
    }
    return {label: (rounded ? '≈' : '') + label, exact, rounded, valid: true};
  } catch {
    return unavailable;
  }
}

export const timeLabel = (value: unknown): string => formatTime(value).label;
