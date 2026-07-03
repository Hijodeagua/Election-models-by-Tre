// Shared display formatters, so margins and probabilities read the same
// everywhere (race cards, charts, tables).

// Dem−Rep margin (positive = D advantage) → "D+3.2" / "R+0.5" / "Even".
// Rounds first so a value like -0.27 at 0 decimals reads "Even", not "R+0".
export function fmtMargin(margin: number | null | undefined, decimals = 1): string {
  if (margin == null) return '—';
  const rounded = Number(margin.toFixed(decimals));
  if (rounded === 0) return 'Even';
  const side = rounded > 0 ? 'D' : 'R';
  return `${side}+${Math.abs(rounded).toFixed(decimals)}`;
}

// Win probability → whole-percent label, clamped so near-certain races read
// ">99%" / "<1%" instead of an overconfident "100%" / "0%".
export function fmtProb(prob: number): string {
  if (prob >= 0.995) return '>99%';
  if (prob <= 0.005) return '<1%';
  return `${Math.round(prob * 100)}%`;
}
