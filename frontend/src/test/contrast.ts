// The contrast of two colours as WCAG 2.1 counts it, for the tests of the look: jsdom
// paints nothing, so axe can't measure it on a page (test/render.tsx).

function channel(value: number): number {
  const c = value / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function luminance(hex: string): number {
  const digits = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((at) => parseInt(digits.slice(at, at + 2), 16))
  return 0.2126 * channel(r!) + 0.7152 * channel(g!) + 0.0722 * channel(b!)
}

/** "#8a8ea6" on "#ffffff" → 3.23. Six-digit colours only. */
export function contrast(one: string, other: string): number {
  const [light, dark] = [luminance(one), luminance(other)].sort((a, b) => b - a)
  return (light! + 0.05) / (dark! + 0.05)
}
