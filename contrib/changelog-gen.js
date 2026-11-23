#!/usr/bin/env node
/**
 * changelog-updater — generate monthly changelog files for the linux-use repo.
 *
 *   node changelog-updater.js generate --month YYYY-MM
 *     Writes docs/changelog-YYYY-MM.html (Product + Technical tabs),
 *     docs/changelog-YYYY-MM-product.md, and inserts the month link into
 *     docs/changelog.html (idempotent).
 *
 *   node changelog-updater.js update-product --month YYYY-MM
 *     Regenerates only docs/changelog-YYYY-MM-product.md from the same
 *     commit grouping (useful after editing the technical view).
 *
 * Run from the repo root (needs docs/ + git history). Conventional-commit
 * prefixes are grouped into headline features; everything else lands under
 * a technical bullet list. The HTML matches the established Geist/Tailwind
 * style of prior months — feature-card product view, tech-item list.
 */

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const month = (() => {
  const i = process.argv.indexOf("--month");
  return i > -1 ? process.argv[i + 1] : null;
})();
const cmd = process.argv[2];

if (!["generate", "update-product"].includes(cmd) || !/^\d{4}-\d{2}$/.test(month || "")) {
  console.error("usage: changelog-updater.js generate|update-product --month YYYY-MM");
  process.exit(1);
}

const repoRoot = process.cwd();
const docsDir = path.join(repoRoot, "docs");
if (!fs.existsSync(docsDir)) { console.error("docs/ not found — run from the repo root"); process.exit(1); }

const MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const [year, mon] = month.split("-");
const monthName = MONTH_NAMES[parseInt(mon, 10) - 1];

function commitsForMonth() {
  const since = `${month}-01`;
  // last day of month: first of next month minus 1 day
  const next = new Date(Date.UTC(+year, +mon)); // mon is 1-indexed already
  const until = next.toISOString().slice(0, 10);
  const raw = execSync(
    `git log main --since=${since} --until=${until} --pretty=format:'%h|%s' --no-merges`,
    { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }
  );
  return raw.split("\n").filter(Boolean).map((l) => {
    const [hash, ...rest] = l.split("|");
    return { hash, subject: rest.join("|") };
  });
}

const GROUPS = [
  { re: /safety|profile|live browser/i, name: "Safety" },
  { re: /cdp|flashbrowse|benchmark|via cdp|dom/i, name: "CDP fast path" },
  { re: /expand|lines|metrics|stats|settle|sweep/i, name: "Perception & expand" },
  { re: /readme|changelog|icon|facelift|brand|guide|skill|docs/i, name: "Docs & branding" },
  { re: /sheetgen|recipes/i, name: "Sheetgen recipes" },
];

function group(commits) {
  const out = new Map(GROUPS.map((g) => [g.name, []]));
  out.set("Other", []);
  for (const c of commits) {
    const g = GROUPS.find((x) => x.re.test(c.subject));
    out.get(g ? g.name : "Other").push(c);
  }
  return out;
}

const PRODUCT_TITLES = {
  "CDP fast path": "CDP fast path — a 60ms eye for web content",
  "Perception & expand": "Perception: below-the-fold coverage, compact output, metrics",
  "Docs & branding": "Docs, README and site updates",
  "Safety": "Safety hardening",
  "Sheetgen recipes": "Sheetgen workflow recipes",
  "Other": "Other changes",
};

function htmlCard(title, body, icon, color) {
  return `        <div class="feature-card rounded-xl p-6 mb-4">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-${color}-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">${icon}</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">${title}</h3>
              <p class="text-white/40 leading-relaxed">${body}</p>
            </div>
          </div>
        </div>`;
}

const ICONS = ["🛡️","📋","🔄","💬","🔬","⚡","📊","🔧","🚀","📦"];
const COLORS = ["emerald","emerald","emerald","emerald","emerald","emerald","emerald","emerald","emerald","emerald"];

function buildHtml(commits, groups) {
  let productCards = "";
  let i = 0;
  for (const [g, list] of groups) {
    if (!list.length) continue;
    productCards += htmlCard(
      PRODUCT_TITLES[g] || `${g} updates`,
      `${list.length} change${list.length > 1 ? "s" : ""} this month — see the technical view for the full list.`,
      ICONS[i % ICONS.length], COLORS[i % COLORS.length]
    ) + "\n\n";
    i++;
  }
  let tech = "";
  for (const [g, list] of groups) {
    if (!list.length) continue;
    tech += `        <h2 class="text-2xl font-semibold text-white mb-6">${g}</h2>\n        <div class="space-y-2 mb-10">\n`;
    for (const c of list) tech += `          <div class="tech-item pl-4 py-1"><span class="text-white/60">${c.subject.replace(/&/g,"&amp;").replace(/</g,"&lt;")}</span></div>\n`;
    tech += "        </div>\n\n";
  }
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Changelog ${monthName} ${year} - linux-use</title>
    <script src="https://cdn.tailwindcss.com"><\/script>
    <link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
    <style>
      body { font-family: 'Geist', system-ui, sans-serif; background-color: #050505; color: #e2e8f0; }
      h1, h2, h3 { font-family: 'Geist', system-ui, sans-serif; }
      .tab-btn { transition: all 0.2s ease; }
      .tab-btn.active { background-color: #1a1a1d; border-color: #22c55e; color: #fff; }
      .tab-content { display: none; animation: fadeIn 0.3s ease; }
      .tab-content.active { display: block; }
      @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
      .feature-card { background: linear-gradient(135deg, #1a1a1d 0%, #151517 100%); border: 1px solid #262629; transition: all 0.3s ease; }
      .feature-card:hover { border-color: #22c55e; transform: translateY(-2px); }
      .tech-item { border-left: 2px solid #262629; transition: border-color 0.2s; }
      .tech-item:hover { border-left-color: #22c55e; }
    </style>
  </head>
  <body class="bg-[#0a0a0b] min-h-screen">
    <div class="max-w-5xl mx-auto px-6 py-24">
      <header class="mb-16">
        <a href="changelog.html" class="inline-flex items-center gap-1 text-sm text-white/30 hover:text-white/70 text-sm mb-6 inline-block transition-colors"><span class="text-xs">&larr;</span> Back to Changelog</a>
        <h1 class="text-5xl font-bold text-white mt-4 tracking-tight">Changelog</h1>
        <p class="text-white/40 mt-3 text-lg">${monthName} ${year}</p>
        <div class="flex gap-2 mt-8">
          <button onclick="switchTab('product')" id="tab-product" class="tab-btn active px-5 py-2.5 rounded-lg border border-slate-700 text-slate-300 font-medium text-sm hover:border-slate-600">Product</button>
          <button onclick="switchTab('technical')" id="tab-technical" class="tab-btn px-5 py-2.5 rounded-lg border border-slate-700 text-slate-300 font-medium text-sm hover:border-slate-600">Technical</button>
        </div>
      </header>
      <div id="content-product" class="tab-content active">
${productCards}      </div>
      <div id="content-technical" class="tab-content">
${tech}      </div>
      <footer class="mt-16 pt-8 border-t border-slate-800 text-white/30 text-sm">Generated ${monthName} ${year}</footer>
    </div>
    <script>
      function switchTab(tab) {
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        document.getElementById('content-' + tab).classList.add('active');
        document.getElementById('tab-' + tab).classList.add('active');
      }
    <\/script>
  </body>
</html>
`;
}

function buildProductMd(groups) {
  let md = `# Changelog — ${monthName} ${year}\n\n## Product\n\n`;
  for (const [g, list] of groups) {
    if (!list.length) continue;
    md += `- **${PRODUCT_TITLES[g] || g}** — ${list.length} change${list.length > 1 ? "s" : ""} this month.\n`;
  }
  return md;
}

function updateIndex() {
  const idx = path.join(docsDir, "changelog.html");
  if (!fs.existsSync(idx)) return;
  let src = fs.readFileSync(idx, "utf8");
  const link = `<a href="changelog-${month}.html"`;
  if (src.includes(link)) return; // idempotent
  const entry = `        <a href="changelog-${month}.html" class="card block rounded-xl p-6">\n          <span class="text-[#86efac] font-medium">${monthName} ${year}</span>\n          <span class="text-gray-500 ml-2 text-sm">&rarr; View</span>\n        </a>\n`;
  src = src.replace(/(<div class="space-y-4">\s*)/, `$1${entry}`);
  fs.writeFileSync(idx, src);
  console.log(`docs/changelog.html: added ${monthName} ${year} link`);
}

const commits = commitsForMonth();
const groups = group(commits);
console.log(`${commits.length} commits in ${monthName} ${year}`);

if (cmd === "generate") {
  const htmlPath = path.join(docsDir, `changelog-${month}.html`);
  fs.writeFileSync(htmlPath, buildHtml(commits, groups));
  console.log(`wrote ${htmlPath}`);
}
const mdPath = path.join(docsDir, `changelog-${month}-product.md`);
fs.writeFileSync(mdPath, buildProductMd(groups));
console.log(`wrote ${mdPath}`);
if (cmd === "generate") updateIndex();
console.log("done");
