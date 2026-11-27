# COCFARM migration audit

Status: second source-level audit pass completed for configuration, search/attack flow, device access, account profiles, emulator management and upstream open PRs/issues. Runtime validation and full module-by-module comparison remain in progress.

## Target decision

Use **COCFARM** as the implementation base. Do not carry over Telegram notifications, the CoC_Bot web dashboard, iPhone Shortcuts, or mandatory third-party AI OCR. Keep local OCR and computer vision. Preserve task-level controls.

## Audited source snapshots

- COCFARM: `BilinP/COCFARM`, `main`, commit `46ddfa032e81baea8a6c62824468bea7c19ee413` (tree inspected 2026-11-28).
- Latest COCFARM release: `v1.9.8`, published 2026-11-23. Its `COCFARM-windows.zip` release asset publishes a SHA-256 digest.
- CoC_Bot: `Syhung2k7dev/CoC_Bot`, `main`, commit `00c400a60a454d971a1132bb3607c04ecde3cd36`.

## Confirmed feature comparison

| Capability | COCFARM | CoC_Bot | Migration note |
|---|---|---|---|
| Home Village farming/search/attack | Present | Present | Keep COCFARM implementation; compare attack strategies and configuration depth later. |
| Builder Base farming | Present | Present | Keep COCFARM implementation; verify edge cases and current game UI compatibility. |
| Building, hero, lab, pet upgrades | Present | Present | COCFARM exposes separate settings and ordering. |
| Hero equipment upgrades | Present (`tasks/equipment.py`, `UpgradeConfig.equipment`) | No equivalent found in inspected source tree | COCFARM advantage; retain. |
| Clan Capital / Raid Weekend | Present (`tasks/capital.py`) | No equivalent module found | COCFARM advantage; retain. |
| Clan War / Ranked | Present (`tasks/war.py`, `tasks/ranked.py`) | No equivalent module found | COCFARM advantage; retain. |
| Clan Games | Present (`tasks/clan_games.py`) | No equivalent module found | COCFARM advantage; retain. |
| Clan troop requests / donations | Present (`tasks/clan.py`, `tasks/donate.py`) | No equivalent module found | COCFARM advantage; retain. |
| Super Troops | Present (`tasks/super_troops.py`) | No equivalent module found | COCFARM advantage; retain. |
| Multiple emulator instances / accounts | Present (`instances.py`, `accounts.py`) | Present | Both support multiple instances and account-specific settings; COCFARM has profile matching by in-game player-name image and shared/per-account config separation. |
| Scheduling / breaks | Present (`ScheduleConfig`, bot scheduler) | Present in a different form (`CHECK_INTERVAL`, idle suspend and task loop) | COCFARM has richer play-window, daily-attack limit, random break and day-off scheduling; CoC_Bot focuses on periodic upgrade/attack checks. |
| Per-task controls | Separate settings across `Config` groups | Central `Task_Handler` exclusion list | COCFARM has most major toggles but not an exact one-to-one model; see detailed comparison below. |
| CV / template matching | OpenCV template matching and image analysis | OpenCV/template matching | Keep COCFARM vision stack unless tests show a concrete regression. |
| Local OCR | Windows OCR for words; custom glyph matching for numbers | EasyOCR locally; native macOS OCR | COCFARM does not need Groq to read ordinary UI text/numbers. |
| External AI OCR | Not required / no provider integration found | Optional Groq + Llama 4 Scout | Exclude from migration scope unless later accuracy tests justify it. |
| Desktop GUI | PySide6 / Fluent Widgets | Desktop GUI | Keep COCFARM GUI as the base. |
| Web Dashboard | Not found in COCFARM main tree | Present | Explicitly out of scope. |
| Telegram notifications | Not found | Present | Explicitly out of scope. |
| iPhone Shortcut | Not found | Present | Explicitly out of scope. |
| Loot history | CSV attack history and GUI history page | Not confirmed equivalent | Keep COCFARM history. |
| Discord notifications | Present | Not confirmed | Optional; user has not asked to remove it. |

“Not found” means no corresponding implementation was identified in the inspected default-branch source; it is not a claim that no experimental branch or external integration exists.

## OCR / CV findings

COCFARM uses three complementary approaches:

1. `farmbot/vision.py`: OpenCV template matching for buttons, icons, cards and UI elements.
2. `farmbot/text.py`: custom digit segmentation and glyph classification for resource counts; glyphs can be learned from screenshots.
3. `farmbot/ocr.ps1` and `farmbot/ocr_lines.ps1`: Windows' built-in OCR for text and text-line positions.

Relevant consumers include `tasks/search.py` (loot numbers) and `tasks/clan_games.py` (challenge text). The README instructs users to set Clash of Clans to English. This means the intended baseline is local OCR + CV, not an external AI service.

## Task exclusion / configuration finding

CoC_Bot's `src/utils.py::Task_Handler` defines a central exclusion vocabulary for home/building/lab/pet upgrades, attacks, assistants and priorities. The exclusion list is obtained from its local or remote GUI endpoint.

COCFARM instead exposes settings directly in its configuration model and GUI, including:
- `upgrade.enabled`, `upgrade.pets`, `upgrade.heroes`, `upgrade.lab`, `upgrade.buildings`, `upgrade.equipment`;
- `builder.upgrade`, `builder.upgrade_heroes`, `builder.upgrade_lab`, `builder.upgrade_buildings`;
- `clan.donate`, `clan.request_troops`, `capital.raid`, `war.enabled`, `ranked.enabled`, `clan_games.enabled`;
- `search.maintain_only` and village mode controls.

Most task groups already have native COCFARM controls. The exact parity is not complete: CoC_Bot has explicit `ATTACK_HOME_BASE` and `ATTACK_BUILDER_BASE` switches, while COCFARM selects `home`, `builder`, or `auto` farming mode and has `search.maintain_only`; it does not expose the same two independent attack booleans in the inspected config. CoC_Bot also has explicit switches to disable priority-based selection (`PRIORITY_*`), whereas COCFARM uses ordered upgrade lists and per-kind filters (`order`, `only`, `research_only`, `equipment_only`) without an equivalent global random-vs-priority toggle found so far. COCFARM's `UpgradeConfig` does expose `apprentice` and `lab_assistant`, matching CoC_Bot's assistant switches. Recommendation: do not port the central exclusion service or GUI/API machinery; add only the missing native settings if the user wants independent attack toggles and a priority-disable option. Keep a central task-exclusion list as optional convenience, not a required migration.

## Initial engineering / security observations

- COCFARM's `farmbot/update.py` checks the release asset size and, when GitHub supplies it, SHA-256. The inspected latest release does supply a SHA-256 digest.
- `unpack()` checks archive paths are under the expected `COCFARM/` root and rejects parent traversal, absolute paths, and colon-containing paths before extraction.
- The updater does not verify a publisher signature; the checksum is obtained from GitHub's release metadata. Treat GitHub account/repository compromise as outside that checksum's protection.
- COCFARM parses TOML with Python's `tomllib`, uses JSON/CSV for local state, and controls emulators through ADB/subprocesses.
- The COCFARM tree has no `tests/` directory in the inspected main commit, although `pyproject.toml` configures pytest and CI builds the Windows executable and runs its `--self-test`. This is not a substitute for a comprehensive unit/integration suite.
- Large modules deserve maintainability review: `farmbot/gui.py` (~406 KB), `farmbot/bot.py` (~136 KB), and `farmbot/tasks/attack.py` (~107 KB). CoC_Bot also has large modules (`src/utils.py`, `src/upgrader.py`), so code size alone is not a reason to transplant its architecture.
- Licensing differs: COCFARM is GPL-3.0-or-later; CoC_Bot is MIT. Any combined distributed derivative must comply with GPL-3.0-or-later and preserve applicable copyright/license notices.



## Second-pass findings: task configuration, emulator and runtime risks

### CoC_Bot exclusion controls vs COCFARM controls

CoC_Bot's `Task_Handler.task_defaults` (in `src/utils.py`) contains these independently overrideable keys:
- Upgrade priority toggles: `home_base_priority`, `home_lab_priority`, `pet_house_priority`, `builder_base_priority`, `builder_lab_priority`.
- Upgrade category toggles: `heroes`, `home_base`, `builder_base`, `home_lab`, `builder_lab`, `pet_house`.
- Farming toggles: `home_attacks`, `builder_attacks`.
- Assistants: `lab_assistant`, `builder_apprentice`.

COCFARM's inspected `farmbot/config.py` already has:
- Home upgrades: `upgrade.enabled`, `pets`, `heroes`, `lab`, `buildings`, `equipment`, plus ordered selection and allow-lists.
- Builder upgrades: `builder.upgrade`, `upgrade_heroes`, `upgrade_lab`, `upgrade_buildings`.
- Assistants: `upgrade.apprentice`, `upgrade.lab_assistant`.
- Clan/other jobs: `clan.request_troops`, `clan.donate`, `capital.raid`, `ranked.enabled`, `war.enabled`, `clan_games.enabled`.
- Farming mode: `BotConfig.mode` supports `home`, `builder`, `auto`; `SearchConfig.maintain_only` stops searching and just maintains the village.

Differences worth considering for a later optional enhancement:
1. Independent Home and Builder attack enable switches are explicit in CoC_Bot; COCFARM's mode selector is not exactly the same control.
2. CoC_Bot can disable priority selection and fall back to random order; COCFARM's upgrade order is explicitly configured and no equivalent priority master-switch was found.
3. COCFARM has broader controls than CoC_Bot for attack strategy, troop deployment, spells, hero walks, war/ranked star focus, and resource thresholds. Do not replace this with CoC_Bot's simpler attack configuration.
4. The user explicitly wants task exclusions retained. Prefer adding a small native COCFARM "disabled tasks" layer only if it improves usability beyond existing per-section switches; do not import its old local/remote HTTP dependency.

### Emulator/device compatibility

- COCFARM `DeviceConfig.mode` supports BlueStacks, LDPlayer, MuMu and manual ADB serial. Its device abstraction is ADB-first and documents that any ADB-exposing emulator or real Android phone can be driven manually.
- CoC_Bot's current config supports BlueStacks, MuMu and LDPlayer. The repository's latest commit specifically added LDPlayer 9 support and multi-instance reliability fixes.
- COCFARM's multi-farm support exists, but current main does not include a shared active-BlueStacks concurrency cap. Open PR #39 proposes such a cap for one COCFARM GUI hub only; it explicitly does not coordinate multiple separate COCFARM processes and does not cap LDPlayer, MuMu or manual devices.
- COCFARM's per-account profiles use the visible player name and keep device/regions/notifications/profile registry shared, while gameplay settings are profile-specific. This is more directly tailored to several Clash of Clans accounts than CoC_Bot's per-instance config structure.

### Upstream PRs not merged into the audited main commit

All three PRs below target COCFARM main commit `46ddfa0` and were open when checked on 2026-11-28. Their code is therefore **not part of the audited main snapshot**:
- [PR #40 — Builder troop count / no-hero deployment](https://github.com/BilinP/COCFARM/pull/40): reports a real Builder Base bug when no hero is unlocked; the proposed patch adds a count guard and stops the farm after uncertain troop-count reads. PR author reports 14 portable tests and two live no-hero attacks, but the fix still depends on cached village metadata.
- [PR #39 — BlueStacks active-instance cap](https://github.com/BilinP/COCFARM/pull/39): optional concurrency cap to reduce memory pressure. Reported validation includes focused offline tests and a bounded live collection-only trial; it does not validate attacks/upgrades under the cap. Not a blanket multi-emulator scheduler.
- [PR #38 — Deploy standalone Clan Castle troops without Siege Machine](https://github.com/BilinP/COCFARM/pull/38): reports a Home Village bug where donated Clan Castle troops are ignored when no siege machine is present. The proposed fix has synthetic tests and two supervised live attacks with different clan emblems.

### Open upstream issues relevant to reliability

At the same time, COCFARM had open issues including:
- [#25 Donation flow bugs](https://github.com/BilinP/COCFARM/issues/25): reports failed donations when Clan Castle capacity fills concurrently, incomplete siege-machine donation and only handling the top request.
- [#29 Donation selection and MuMu zoom issues](https://github.com/BilinP/COCFARM/issues/29): reports missed donation troop selection and zoom-out failures on MuMu.
- [#30 Royal Champion walk issues](https://github.com/BilinP/COCFARM/issues/30): reports missed Invisibility Spell placements and Rocket Spear level handling.
- [#22 Spell placement randomness](https://github.com/BilinP/COCFARM/issues/22): reports spell placement not behaving as configured.
- [#40 no-hero Builder deployment](https://github.com/BilinP/COCFARM/issues/40) is addressed by open PR #40, not by audited main.
- [#38 standalone Clan Castle troop detection](https://github.com/BilinP/COCFARM/issues/38) is addressed by open PR #38, not by audited main.

These issue reports are not proof that every user will reproduce the bugs. They are concrete test cases that should be covered before calling the migration stable. Donation and spell deployment deserve particular attention because the upstream issue list includes several reports in those areas.

### Tests and CI clarification

The inspected COCFARM main tree has no committed `tests/` directory, although the project configures pytest and CI builds the Windows executable and runs its packaged `--self-test`. The open PRs above include or describe additional focused tests in their contribution branches. Do not confuse those PR-only tests with tests already present in main. The migration branch should add a maintained regression suite before merging these fixes.

## Updated next steps

1. Complete exact settings parity and GUI wiring, especially independent attack toggles and priority-disable behavior.
2. Review PR #38, #39 and #40 patches against main; selectively port only after checking dependencies and tests.
3. Audit donation, spell placement, Royal Champion walk, Builder no-hero deployment and MuMu zoom regressions.
4. Finish detailed module review of attack/deployment, upgrades, scheduler, device recovery, multi-instance lifecycle, persistence and GUI.
5. Build regression tests around real screenshots and synthetic cases; then run bounded emulator validation.
6. Only after those checks, begin feature integration and cleanup on the user's own migration branch. Do not edit upstream COCFARM.


## Additional feature differences found in attack controls

The default CoC_Bot config has two controls that are not represented one-to-one in the inspected COCFARM config/form:
- `EXCLUDE_CLAN_TROOPS`: CoC_Bot can skip cards it classifies as donated Clan Castle troops during Home attacks. COCFARM's `armybar.py` classifies troop/spell/single/siege cards and its attack loop deploys troop cards; no equivalent user-facing skip-donated-troops switch was found. COCFARM does have separate Clan Castle lure logic for star-focused attacks, which is not the same control.
- `ATTACK_SLOT_RANGE`: CoC_Bot can limit deployment to a configured range of troop-bar slots and scroll the bar to continue scanning. No corresponding slot-range control was found in COCFARM. COCFARM's deployment loop is more sophisticated in other respects: it reads troop counts again, checks whether units actually deployed, retries rejected points, and can fall back to fixed deployment lines.

These are real CoC_Bot-only configuration features found in code, but their practical importance is optional. If retained, implement them as native COCFARM attack settings, with safe defaults preserving current COCFARM behavior (deploy all eligible cards; do not silently exclude donated troops).

## Attack automation comparison

- COCFARM has much richer deployment strategy settings: side selection, spread vs loot-oriented deployment, waves, troop/wave pacing, siege use, super troop boosts, hero abilities by delay/health, hero walks, Spirit Fox timing, spell selection/placement, Earthquake paths, funneling, star-focused deployment, league bonus farming, early battle exit conditions, and optional human-like deployment rhythms.
- CoC_Bot's attack controls are simpler: global troop deployment timing, selected troop-card slot range, and optional exclusion of donated Clan Castle troops. Its attack path uses screenshot/template detection, card-edge profiling and batch deployment; after attacks it closes/restarts the game app to complete the battle.
- COCFARM also has game-update handling: its bot detects the game's Play Store "new version" window and invokes the game-update path. CoC_Bot README mentions automatic game app updates, but no matching implementation was confirmed in the inspected source files yet; keep this item marked for follow-up rather than asserting parity.
- COCFARM's `maintain_only` setting is a Home Village no-attack mode: `Bot.cycle()` still runs village maintenance and pre-farming war/ranked jobs, then skips the normal Home attack. It does not provide an equivalent independent Builder Base attack-off switch: `builder_cycle()` proceeds to `builder.attack()` after its maintenance/upgrades unless the round is diverted/stopped for another reason. CoC_Bot explicitly has both `ATTACK_HOME_BASE` and `ATTACK_BUILDER_BASE`. This is a concrete migration gap for users who want Builder Base upgrades/collection without Builder attacks.

## Current migration candidates (not yet implemented)

Priority candidates, based on actual differences rather than copying CoC_Bot wholesale:
1. Add `builder.attack_enabled` to COCFARM's config, form model, GUI, example TOML, validation and builder cycle. Default `true` to preserve current behavior.
2. Consider an explicit `home.attack_enabled` switch instead of relying only on `search.maintain_only`, if a clearer paired control is preferred.
3. Consider `attack.exclude_clan_troops` and `attack.slot_start/slot_end` as optional controls only if the user wants those CoC_Bot behaviors. Defaults must preserve COCFARM's current all-card behavior.
4. Consider an optional priority master-switch that selects randomly when disabled; do not replace COCFARM's richer ordered allow-lists.
5. Assess PR #39's BlueStacks-only concurrency cap separately; its limitations must be visible in the GUI.


## Other CoC_Bot-only operational options

The CoC_Bot template config also contains:
- `SUSPEND_EMULATOR_ON_IDLE`: optional emulator process suspension during idle periods to reduce resource use. COCFARM has `human.offline_breaks`, which closes the Clash of Clans app during breaks/outside playing hours, but no equivalent emulator-suspend setting was found. These are not the same behavior.
- `DISABLE_DEVICE_SLEEP`: keeps the host PC awake while the bot runs (Windows/macOS-specific implementation). No matching host-sleep prevention setting was found in COCFARM's config/form. This may be useful for long unattended runs but should be an opt-in feature with clear battery/power implications.
- macOS desktop/runtime support. COCFARM's current GUI, Windows OCR PowerShell scripts, scheduled-task wake-up and emulator adapters are Windows-oriented. This is not a practical loss if the target machine is Windows.

COCFARM already has automatic emulator launch, emulator standardization, automatic game restart and emulator recovery, plus an optional Windows Task Scheduler wake-up between upgrades. CoC_Bot's emulator suspend feature should be considered separately; do not assume COCFARM automatically shuts down or suspends the emulator when idle. COCFARM's offline-break setting closes the game app, not the emulator VM.


## Third-pass deep dive: Clan donations, Builder Base deployment and PR review

### Clan donation implementation (COCFARM main)

The current main implementation in `farmbot/tasks/donate.py` is substantially more complete than the older open bug reports alone suggest:
- Detects donation cards using image matching against local troop-picture assets and classifies available/greyed-out cards by saturation.
- Reads the requester's Clan Castle room from the request bubble using local glyph OCR, then chooses a preset army for the matching Castle level when no explicit main troop list is configured.
- Supports prioritized main troops, optional fill with the largest eligible troop, selected Siege Machines, selected spells, and request-specific troop lists.
- Pages horizontally through troop/spell cards, flicks to the end for Siege Machines, and returns to earlier pages when filling is needed.
- Detects gem-priced donation mode and refuses to spend gems.
- Checks whether each tap actually changed donation counters / donated-unit strip; retries one missed tap and raises `Refused` when the request filled or the game refuses the donation.
- Iterates multiple chat requests (up to `MAX_OPENS = 12`) and tracks already handled request bubbles so new/moved requests can be handled without looping forever.
- Clan request flow reads the request cooldown and waits out short cooldowns; it also has a separate Army-window request path when configured to empty the Castle first.

This is evidence that COCFARM has the donation features that were missing or unreliable in older versions. However, issue [#25](https://github.com/BilinP/COCFARM/issues/25) and [#29](https://github.com/BilinP/COCFARM/issues/29) remain open in the upstream issue tracker as checked on 2026-11-28. #25 reports concurrent-fill refusal/crash, Siege Machine paging, only donating to the top request, slow request cooldown handling; #29 reports certain troop cards not being clicked and MuMu zoom-out failure. The current code contains explicit handling for each of the donation workflow features described, but no committed main-branch automated donation regression suite was found. Do not assume those user-reported cases are fully resolved until the exact scenarios are replayed against the current release and main.

### Clan Castle donated troops during attacks: PR #38

PR #38 is a targeted fix for a distinct attack-bar recognition bug. The current army-bar classifier distinguishes counted troops, spells, heroes, Siege Machines and empty slots. The PR adds a separate `castle` card type for standalone Clan Castle troops (cyan frame, no level badge), avoids mistaking the Clan emblem for a Siege Machine level badge, treats it as a single-deployment card, and prevents Siege Machine/hero ability logic from being applied to it.

The PR adds synthetic OpenCV tests for different Clan emblems, dashed empty slots, Siege Machine toggle behavior, successful/refused deployment, and single deployment dispatch. These are useful offline regression tests with synthetic pixels rather than player screenshots. They do not replace a live supervised test across supported emulator scales/themes, but they are meaningful coverage. The fix should be reviewed for integration and likely adopted after validating its base/head compatibility; it directly addresses a real missing case in the current attack recognition path.

### Builder Base no-hero deployment: PR #40

PR #40 addresses a serious correctness issue: without a Builder Base hero, the bot's old first-troop position was offset incorrectly and the deployment loop treated a card as a single unit rather than reading its count. The proposed patch:
- Loads cached village/hero metadata before deciding the Builder Base hero layout.
- Shifts the first troop slot left when there is no hero.
- Reads troop counts with local glyph recognition and validates confidence/range.
- Verifies that each deployment reduced the count before continuing.
- If the count is unknown or an input's effect is uncertain, stops further deployments, saves the error screen and waits for the natural battle result instead of blindly retrying.
- Adds synthetic tests for no-hero/hero cases, counted troops, unknown counts, uncertain first taps and preventing automatic recovery/re-admission after uncertain deployment.

This is a safety/correctness-oriented patch and should be strongly considered for adoption after a focused code review. Its key invariant is important: an uncertain deployment must not be replayed automatically, since that could send unintended additional troops.

### BlueStacks concurrency cap: PR #39

PR #39 is not a general emulator limit. It adds a per-COCFARM-window queue for BlueStacks farms only, with verified ownership/exit checks, queueing, pause/stop behavior, round handoff, held slots when cleanup cannot be verified, and a per-PC setting. It explicitly does not cap LDPlayer, MuMu or manual ADB devices and does not coordinate separate COCFARM processes.

The PR adds a comparatively broad synthetic test set covering queue fairness, dynamic limit changes, worker lifecycle, startup cancellation, ownership/exit ambiguity, GUI behavior and round handoff. This is useful if several BlueStacks instances are run simultaneously on a RAM-limited PC. It is optional and should not be ported blindly: the process inventory and native window-title ownership logic are Windows/BlueStacks-specific and add substantial complexity. First establish whether the user's actual emulator count and RAM pressure justify it.

### Current risk ranking after this pass

1. **High: troop deployment correctness** — adopt/review PR #38 and #40, then validate against live game screens.
2. **High: donation regression scenarios** — despite a mature implementation, open issues #25/#29 and lack of committed main-branch tests justify targeted tests and supervised runs.
3. **Medium: multi-BlueStacks memory pressure** — PR #39 is optional, scoped, and complex; only adopt if needed.
4. **Medium: spell placement and Royal Champion walk** — issue #22 and #30 remain concrete scenarios to reproduce and test.
5. **Low for the current Windows target: macOS support** — no need to port CoC_Bot's macOS-specific code.

### Next source audit tasks

1. Trace all PR #38 and #40 changed lines against the audited main snapshot and verify their patches apply cleanly to the exact current base.
2. Review donation issue #25/#29 against current donation code and create tests for full-while-donating, paging to Siege Machines, multiple requests, and request cooldown.
3. Audit spell placement and Royal Champion walk against issues #22/#30.
4. Check game-update flow and all emulator recovery branches.
5. Then implement only the accepted migration gaps on the user's own branch, with config/form/example/validation/tests updated together.


## Fourth-pass deep dive: spell placement and Hero Walk

### Spell placement (issue #22)

Current COCFARM main contains explicit mechanisms for both modes:
- `spell_placement = "together"`: one common point selected by `spell_spot`; the default is `"random"`, chosen inside the middle portion of the base and deliberately kept away from the previous battle's spot when possible.
- `spell_placement = "spread"`: points are distributed around the base using a golden-angle sequence with a randomized starting angle and small per-point jitter. This is designed to avoid a straight line and distribute spells around the deploy ring.
- Star-focused battles derive the spell point from the attack push direction and configured depth; the random variant perturbs around that push point.
- Earthquake spells have separate path/spot targeting and a configurable count per opening point; funneling can send a small troop/hero group ahead of the main army.

This is a substantial algorithmic answer to the behavior described in open issue [#22](https://github.com/BilinP/COCFARM/issues/22). However, the issue remains open and no committed automated test suite for screenshot-derived spell coordinates was found in main. Verify that the GUI maps the "Together/Spread" and "Random/Middle" settings correctly, then replay repeated attacks with identical bases and record the coordinates. A code-level random generator does not by itself prove the deployed coordinates are valid or sufficiently varied.

### Royal Champion / Archer Queen Hero Walk (issue #30)

The current `farmbot/tasks/walk.py` contains a detailed visual tracking and timing system:
- Detects the hero from her health bar, card hue and level badge; pale/hidden sightings are confirmed across multiple looks.
- Tracks movement direction from recent sightings, predicts forward only for a bounded time window, and refuses to cast at stale/unknown locations.
- Places Invisibility ahead of a moving hero, bounded by the spell circle's radius, rather than repeatedly targeting the last seen coordinate.
- Detects when she leaves the current spell circle and can queue another spell before the old coverage expires.
- Detects likely missed spells from health loss and from the hero remaining visible after the expected landing time; avoids repeatedly using the same failed coordinate.
- Accounts for Spirit Fox invisibility/cooldown timing and can use the Royal Champion's Rocket Spear level from the village export to decide when to fire her ability early.
- Uses frequent looks (nominally 0.1 s) to track health and location; the algorithm has multiple thresholds and heuristics calibrated in comments against observed in-game behavior.

These code paths directly target the failure modes described by issue [#30](https://github.com/BilinP/COCFARM/issues/30): stale coordinates, spells landing behind a moving Champion, leaving the invisibility circle, and Rocket Spear level not being considered. Yet #30 is still open in the issue tracker. The implementation is complex and heuristic; without replaying the reported scenarios, do not mark the issue resolved. This is one of the highest-value live-validation areas because a mistaken sighting can waste spells and cause the hero to fall early.

### Deployment point detection

The Home attack path does not rely on one fixed deployment line alone:
- First tries the red deploy boundary via HSV/shape checks (`redline.py`).
- Finds the building area via bright grass, building clusters, and texture analysis (`deployzone.py`) for maps/sceneries where grass color is unreliable.
- Excludes UI regions and screens points based on surrounding ground/obstruction.
- Uses fixed per-side lines as a last-resort fallback.
- Checks whether troops actually deployed by re-reading the troop card/count; if no first deployment succeeds and the screen is still zoomed in, it attempts a forced zoom-out and recalculates points once.

This is a layered strategy and materially more sophisticated than CoC_Bot's simpler card/edge deployment path. Its weakness is reliance on screen appearance, scale, scenery and template/glyph calibration; regression fixtures should include grass, city/stone/snow scenery, low Town Hall layouts, zoomed-in views and UI overlays.

### Game update flow

COCFARM's `farmbot/gameupdate.py` is a separate Android UIAutomator-based update flow:
- Recognizes the game's update dialog from OCR text and the Update button.
- Opens the Play Store, uses UIAutomator XML to find Update/Open/Play controls, and watches the installed package version.
- Handles unsigned-in Play Store, no-update state, long installs, stopping/restarting the game after install, and a long first-load wait.
- The updater is not a generic app store installer; it is specific to the Clash of Clans package and Android Play Store behavior.

CoC_Bot's README claims automatic game updates, but no equivalent implementation was confirmed in the inspected CoC_Bot source paths. This is currently a COCFARM strength; test with a controlled emulator/update state rather than trying to trigger a real game update during ordinary farming.

### Updated risk ranking

1. **High: live deployment correctness** — PR #38 and #40 are not in audited main; review and selectively integrate, then validate.
2. **High: donations** — current code has robust workflow logic, but open #25/#29 and no committed focused tests leave important race/paging cases unproven.
3. **High: Hero Walk** — the code contains specific fixes for #30, but the issue remains open; verify on a controlled test account.
4. **Medium: spell placement** — algorithms address #22, but validate actual coordinate diversity and placement on real layouts.
5. **Medium: multi-emulator RAM cap** — PR #39 is optional and BlueStacks-only; do not adopt unless needed.
6. **Medium: scenery and zoom robustness** — test all deployment-point detection fallbacks across emulator resolutions and map themes.

## Current decision after four audit passes

COCFARM remains the better functional base for the intended Windows desktop migration. The code review so far has not uncovered a reason to reverse the platform choice. However, this is still a source-level assessment: do not call the migrated bot stable until the deployment PRs are reviewed, the open donation/attack reports are reproduced or disproven, and bounded emulator tests pass.

