/**
 * Measure WCAG contrast ratios for principal pairs in src/styles/tokens.css.
 * Outputs JSON to stdout; writes test-results/contrast-ratios.json when run from repo root.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const tokensPath = path.join(root, "src/styles/tokens.css");
const css = fs.readFileSync(tokensPath, "utf8");

function parseTokens(source) {
  const map = {};
  const re = /--([a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})\s*;/g;
  let m;
  while ((m = re.exec(source))) {
    map[`--${m[1]}`] = m[2].toUpperCase();
  }
  return map;
}

function expandHex(hex) {
  let h = hex.replace("#", "").toUpperCase();
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (h.length === 8) h = h.slice(0, 6); // ignore alpha for solid tokens
  return h;
}

function srgbToLinear(c) {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hex) {
  const h = expandHex(hex);
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  const R = srgbToLinear(r);
  const G = srgbToLinear(g);
  const B = srgbToLinear(b);
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

function contrastRatio(fg, bg) {
  const L1 = relativeLuminance(fg);
  const L2 = relativeLuminance(bg);
  const lighter = Math.max(L1, L2);
  const darker = Math.min(L1, L2);
  return (lighter + 0.05) / (darker + 0.05);
}

function round(n) {
  return Math.round(n * 100) / 100;
}

const t = parseTokens(css);

// Principal UI pairs used in product chrome (documented as design intent in tokens)
const pairs = [
  // Light surfaces (paper / porcelain)
  { name: "ink on paper", fg: t["--opn-ink"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "ink on porcelain", fg: t["--opn-ink"], bg: t["--opn-porcelain"], role: "text-normal" },
  { name: "ink-soft on paper", fg: t["--opn-ink-soft"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "ink-soft on porcelain", fg: t["--opn-ink-soft"], bg: t["--opn-porcelain"], role: "text-normal" },
  { name: "neutral-400 on paper", fg: t["--opn-neutral-400"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "neutral-400 on porcelain", fg: t["--opn-neutral-400"], bg: t["--opn-porcelain"], role: "text-normal" },
  { name: "neutral-300 on paper", fg: t["--opn-neutral-300"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "gold-text on paper", fg: t["--opn-gold-text"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "gold-text on porcelain", fg: t["--opn-gold-text"], bg: t["--opn-porcelain"], role: "text-normal" },
  { name: "gold on paper (raw brand gold)", fg: t["--opn-gold"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "blue-mid on paper", fg: t["--opn-blue-mid"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "or-deep on paper", fg: t["--or-deep"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "sem-ok on paper", fg: t["--sem-ok"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "sem-info on paper", fg: t["--sem-info"], bg: t["--opn-paper"], role: "text-normal" },
  // Dark chrome (night / blue)
  { name: "paper on night", fg: t["--opn-paper"], bg: t["--opn-night"], role: "text-normal" },
  { name: "porcelain on night", fg: t["--opn-porcelain"], bg: t["--opn-night"], role: "text-normal" },
  { name: "cyan on night", fg: t["--opn-cyan"], bg: t["--opn-night"], role: "text-normal" },
  { name: "cyan-light on night", fg: t["--opn-cyan-light"], bg: t["--opn-night"], role: "text-normal" },
  { name: "gold-bright on night", fg: t["--opn-gold-bright"], bg: t["--opn-night"], role: "text-normal" },
  { name: "gold-light on night", fg: t["--opn-gold-light"], bg: t["--opn-night"], role: "text-normal" },
  { name: "gold on night", fg: t["--opn-gold"], bg: t["--opn-night"], role: "text-normal" },
  { name: "or-light on night", fg: t["--or-light"], bg: t["--opn-night"], role: "text-normal" },
  { name: "paper on blue", fg: t["--opn-paper"], bg: t["--opn-blue"], role: "text-normal" },
  { name: "cyan on blue", fg: t["--opn-cyan"], bg: t["--opn-blue"], role: "text-normal" },
  { name: "gold-bright on blue", fg: t["--opn-gold-bright"], bg: t["--opn-blue"], role: "text-normal" },
  // UI / non-text (3:1)
  { name: "blue-mid border on paper (UI)", fg: t["--opn-blue-mid"], bg: t["--opn-paper"], role: "ui" },
  { name: "neutral-400 border on paper (UI)", fg: t["--opn-neutral-400"], bg: t["--opn-paper"], role: "ui" },
  { name: "neutral-300 border on paper (UI)", fg: t["--opn-neutral-300"], bg: t["--opn-paper"], role: "ui" },
  { name: "neutral-200 border on paper (UI)", fg: t["--opn-neutral-200"], bg: t["--opn-paper"], role: "ui" },
  // Severity on light
  { name: "sev-low on paper", fg: t["--sev-low"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "sev-medium on paper", fg: t["--sev-medium"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "sev-high on paper", fg: t["--sev-high"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "sev-critical on paper", fg: t["--sev-critical"], bg: t["--opn-paper"], role: "text-normal" },
  // Product deep on light
  { name: "nx-deep on paper", fg: t["--nx-deep"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "co-deep on paper", fg: t["--co-deep"], bg: t["--opn-paper"], role: "text-normal" },
  { name: "ra-deep on paper", fg: t["--ra-deep"], bg: t["--opn-paper"], role: "text-normal" },
];

const rows = pairs.map((p) => {
  const ratio = contrastRatio(p.fg, p.bg);
  const r = round(ratio);
  const aa_normal = r >= 4.5;
  const aa_large = r >= 3.0;
  const aa_ui = r >= 3.0;
  let verdict;
  if (p.role === "ui") {
    verdict = aa_ui ? "PASS AA UI (3:1)" : "FAIL AA UI (3:1)";
  } else {
    if (aa_normal) verdict = "PASS AA normal (4.5:1)";
    else if (aa_large) verdict = "FAIL AA normal; PASS AA large/UI (3:1)";
    else verdict = "FAIL AA normal and large/UI";
  }
  return {
    name: p.name,
    fg: p.fg,
    bg: p.bg,
    role: p.role,
    ratio: r,
    aa_normal_4_5: aa_normal,
    aa_large_or_ui_3: aa_large,
    verdict,
  };
});

const payload = {
  standard: "WCAG 2.x AA",
  thresholds: { text_normal: 4.5, text_large_and_ui: 3.0 },
  source: "src/styles/tokens.css",
  algorithm: "relative luminance sRGB (WCAG 2)",
  tokens_sampled: Object.keys(t).length,
  pairs: rows,
  failing_normal_text: rows.filter((r) => r.role === "text-normal" && !r.aa_normal_4_5),
  failing_ui: rows.filter((r) => r.role === "ui" && !r.aa_large_or_ui_3),
};

const outDir = path.join(root, "test-results");
fs.mkdirSync(outDir, { recursive: true });
const outPath = path.join(outDir, "contrast-ratios.json");
fs.writeFileSync(outPath, JSON.stringify(payload, null, 2));
console.log(JSON.stringify(payload, null, 2));
console.error(`Wrote ${outPath}`);
