---
name: sheetgen-workflow
description: END-TO-END runbook for generating images for FREE via sheetgen (the browser-driven Gemini pattern in linux-use) — from "I need N images" to "images committed in the repo". Use this whenever a task needs many images, thumbnails, avatars, icons, posters or illustrations and the goal is to produce them unattended, safely and without spending money or getting the IP flagged. Covers prompt→batch→session→account-policy→pacing→post-process→commit, plus every operational guardrail and what to do when something breaks. For the mechanical reference (grid math, cut options, keying) use the sheetgen skill instead.
tags: image-generation,sheetgen,free-images,batch,workflow,runbook,gemini,thumbnails,assets,no-api-key,browser-automation
---

# sheetgen-workflow — generate images for free, end to end

**The browser is the API.** sheetgen drives a Google account that is already
signed into Chrome, on a private virtual display, and captures generated
images off the screen. No API key, no billing, no LLM supervising the loop.

Code: `~/ai/machin-linux-use/contrib/sheetgen/`
Reference skill (mechanics, traps, grid math): `sheetgen`

---

## 0. Read this before doing anything

Three hard truths that shape the whole workflow:

1. **Speed is the enemy.** Machine-fast automation gets the machine's IP
   CAPTCHA-flagged by Google, which blocks ALL generation until a human
   solves it once. The tool paces like a human (jittered 2–6s between
   actions, 6–12s between images). Do NOT "optimize for speed". Do NOT lower
   `GEN_MIN_DELAY`/`GEN_MAX_DELAY` to make it faster.
2. **Some accounts are precious.** sheetgen reads
   `~/.config/sheetgen/accounts.json` (`{"preferred": ..., "blacklist":
   [...]}`) and will switch to the preferred account and refuse to generate
   on a blacklisted one. Respect it. Never try to "work around" the blacklist.
3. **Generation is resumable and cheap to retry; CAPTCHA-solving is not.**
   Re-running the same command picks up where it stopped. If the page says
   "unusual traffic from your computer network", stop and get a human to
   solve the CAPTCHA once — it clears for the whole IP.

---

## 1. Decide the shape: grid sheet vs individual images

- **Many DIFFERENT images** (thumbnails for 100 tools, one-off pictures):
  use `--batch` — a JSON list, one generation each. This is the common
  agent case.
- **Many assets from ONE visual style** (sprites, icons, tiles, portraits
  in a consistent style): use job files with a `grid` — one prompt produces
  N×N assets cut into files. See the `sheetgen` skill for grid math.

---

## 2. Write the batch file

```json
[
  {"name": "alpha", "prompt": "a red fox, flat vector style", "out": "art/alpha.png", "size": 600, "edge": 14},
  {"name": "beta",  "prompt": "a blue whale, flat vector style", "out": "art/beta.png",  "size": 600, "edge": 14, "retries": 5}
]
```

Per-item keys: `name` (used for skip/resume), `prompt`, `out` (path),
`size` (longest side; 0 = keep page size), `edge` (corner trim; 14 default),
`timeout` (seconds), `retries` (default 3).

**Prompt craft for card/thumbnail images**: name the subject, the style, and
"clean, centered composition, square format". Add "no text, no watermark" to
avoid model-added labels. A prompt built from the item's title + description
works well.

---

## 3. Dry-run first, then generate

```sh
SG=~/ai/machin-linux-use/contrib/sheetgen

# what would be generated (no browser needed for this part)
$SG/run.py --batch jobs/images.json --dry-run

# generate everything missing (session auto-started, account policy enforced)
$SG/run.py --batch jobs/images.json --ensure-session --json
```

- `--ensure-session` brings the browser session up itself (and restarts it
  between retries). You do not need `session.sh up`/`down` by hand.
- `--json` emits one NDJSON line per image (`{"name","status","ok"}`) —
  parse that, not stderr chatter.
- Existing outputs are skipped automatically. Re-running after a failure
  only does the missing ones.

---

## 4. The account policy (automatic, but know it)

Config: `~/.config/sheetgen/accounts.json` (override `$GEN_ACCOUNTS`):
```json
{"preferred": "groundswallentine", "blacklist": ["arancibiajav"]}
```
- `preferred` / `blacklist` are substring matches against the signed-in email.
- With `--ensure-session`, the browser is switched to `preferred` before any
  generation. A blacklisted account is never generated on; if the switch
  away fails, the run aborts (exit 3).
- Diagnostics:
  - `$SG/session.sh account` — who is signed in
  - `$SG/session.sh switch <substr>` — switch manually
  - `$SG/session.sh status` — display/wm/browser/account

---

## 5. What happens when things go wrong (and it WILL)

| Symptom | Cause | Response |
|---|---|---|
| `composer not found` | session died / page state | `--ensure-session` retries with session restart automatically |
| `image vanished` / `blank frame` | capture race | retried by re-capturing the SAME image (no extra quota). Re-run the command. |
| `Image Generation Limit Reached` | daily account quota | NOT retryable. Stop, report, resume the same command tomorrow. |
| `unusual traffic from your computer network` | IP CAPTCHA-flagged | STOP. Human solves the CAPTCHA once in the browser; then it clears for the whole IP. |
| exit 3 + `account policy:` / `account check:` | wrong/blacklisted account | Check `session.sh account`; the policy is doing its job — don't bypass it. |

---

## 6. Post-process and commit

Images come out as PNG at the page's aspect ratio (batch items keep the
model's ratio unless `size` is set). For web thumbnails, convert + resize +
squarify with your normal image tooling (e.g. `cwebp -q 80 -resize 600 600`),
then commit the source-controlled copies. Captured sheets are scratch —
never commit `docs/sheets/`.

**For a product that serves thumbnails from a server**: after generating,
upload to the server's source-mounted static dir (NOT the container), update
any DB fields pointing at the old assets, verify the URLs return the right
content type, and commit. See the crevisto thumbs workflow in its repo for
the full example.

---

## 7. Rules agents must never break

1. Never lower the pacing delays to "go faster".
2. Never try to generate on a blacklisted account, even by hand.
3. Never commit captured sheets (`docs/sheets/`).
4. Never `pkill -f` a browser flag — it can kill the human's browser.
5. Never carry a linux-use ref between shell commands — look up + act in one call.
6. If the IP gets CAPTCHA-flagged, stop and get a human; do not retry in a loop.
7. If a generation fails, re-run the SAME command (it resumes); don't rewrite the batch.
