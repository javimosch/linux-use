
        <div class="feature-card rounded-xl p-6">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-blue-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">🖱️</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">Control a Linux desktop from an agent</h3>
              <p class="text-white/40 leading-relaxed">linux-use reads the AT-SPI2 accessibility tree and acts on it: list apps and windows, enumerate interactive elements, click, type, send key combos, and read text back. No screenshots, no pixel coordinates, no LLM inside — your agent is the loop. One 154 KB static binary with no runtime dependencies.</p>
            </div>
          </div>
        </div>

        <div class="feature-card rounded-xl p-6">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-emerald-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">🎯</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">Act on widgets, not pixels</h3>
              <p class="text-white/40 leading-relaxed">The <code>act</code> command invokes a widget's own accessible action — no focus stealing, no pointer movement, and it works even when the window is completely hidden behind another window. Synthetic XTEST clicking is there as a fallback for widgets that expose no action.</p>
            </div>
          </div>
        </div>

        <div class="feature-card rounded-xl p-6">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-amber-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">🔒</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">Stale references are detected, never guessed</h3>
              <p class="text-white/40 leading-relaxed">Every element reference carries a fingerprint of its role and name. When the UI changes underneath one, you get exit code 83 and a suggestion to re-read the screen — instead of an action silently landing on the wrong widget. Elements whose identity cannot be proven are reported as unusable rather than emitted as a plausible guess.</p>
            </div>
          </div>
        </div>

        <div class="feature-card rounded-xl p-6">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-purple-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">📡</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">Wait for the UI instead of polling it</h3>
              <p class="text-white/40 leading-relaxed">The <code>watch</code> command streams real AT-SPI events as newline-delimited JSON, one line per event, with a resolved element reference. Filter by app, by role, or by event type; stop after exactly N events or after a time limit. Filtering to a single role took one sample run from 54 events down to the 6 that mattered.</p>
            </div>
          </div>
        </div>

        <div class="feature-card rounded-xl p-6">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">⚡</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">Server-side queries when they actually help</h3>
              <p class="text-white/40 leading-relaxed">Asking for a specific role runs an AT-SPI collection query that matches server-side in one round trip — measured at 5 ms versus 47 ms on a large app. Asking for everything still uses a tree walk, because that turned out to be a wash. The tool picks based on the measurement and tells you which path it took.</p>
            </div>
          </div>
        </div>

        <div class="feature-card rounded-xl p-6">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-rose-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">🔊</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">Incomplete answers are loud, not silent</h3>
              <p class="text-white/40 leading-relaxed">A tree read that was cut short by a depth or node limit says so — in the JSON and on stderr. This came from a real bug: the old default depth silently returned zero text fields for a text editor, which would lead an agent to conclude the editor had none.</p>
            </div>
          </div>
        </div>

        <div class="feature-card rounded-xl p-6">
          <div class="flex items-start gap-4">
            <div class="w-12 h-12 rounded-lg bg-indigo-500/10 flex items-center justify-center flex-shrink-0">
              <span class="text-2xl">🤖</span>
            </div>
            <div>
              <h3 class="text-xl font-semibold text-white mb-2">Built to the agent-first CLI specs</h3>
              <p class="text-white/40 leading-relaxed">JSON on stdout, context on stderr, semantic exit codes, and typed errors that carry <code>recoverable</code> plus concrete <code>suggestions</code>. <code>guide</code> ships the whole operator manual inside the binary, and a warm-registry daemon keeps repeated calls fast. Follows the specs at cli-specs.intrane.fr.</p>
            </div>
          </div>
        </div>
