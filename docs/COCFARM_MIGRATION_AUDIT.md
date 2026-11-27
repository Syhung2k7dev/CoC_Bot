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



## Fifth-pass deep dive: upgrade engine and progression tracking

### COCFARM upgrade architecture

The COCFARM upgrade engine is not just a loop over fixed screen coordinates. The inspected source shows:
- Reads the game's live Build list, applies resource/type filters and sorts by Cost Max, then identifies affordable rows.
- Separately handles new/unbuilt buildings, Town Hall prerequisites, walls, hero upgrades, pets, laboratory research and Hero Equipment.
- Uses a configurable ordered list of upgrade categories and optional ordered allow-lists for buildings, research and equipment.
- Tracks remaining resource budgets between upgrades so it does not repeatedly assume the original storage amount is still available.
- Reads builder availability and laboratory availability, can retain a chosen number of builders, and keeps a builder free for walls when configured.
- Avoids spending gems: an upgrade window with a gem price is closed unpaid.
- Detects locked upgrades and passes over rows that repeatedly fail rather than tapping them every round.
- Uses an account-specific upgradable survey saved beside the village export, invalidated when Town Hall/Laboratory levels change and refreshed daily.
- Assigns Builder's Apprentice and Lab Assistant to eligible ongoing work.
- Handles Builder Base separately with its own resource budgets, builders and Star Laboratory.

### CoC_Bot upgrade comparison

CoC_Bot has the core upgrade categories and user-defined priority lists for Home and Builder Base. It also has explicit booleans for priority-vs-random behavior and a maximum number of upgrades per check. Its implementation is more coordinate/template-driven and has repeated OCR/template searches for builder counts and lab availability.

COCFARM's upgrade flow is more integrated with the live Build list and current village export. It has category ordering, name allow-lists, resource accounting, Town Hall/new-building handling, walls hand-off, equipment/ore upgrades, daily surveys and helper assignment. CoC_Bot's explicit random-order fallback is a small convenience gap, not a reason to transplant its upgrader. If desired, add a native COCFARM use_priority_order setting later; default it on so current behavior is preserved.

### Potential upgrade risks to validate

1. OCR/template recognition of the Build list rows and prices after game UI updates.
2. Correct resource budget tracking when several upgrades start in one round and resources are spent concurrently.
3. Town Hall prerequisite handling and newly unlocked buildings after Town Hall upgrades.
4. Builder limits and keeping one builder free for walls.
5. Hero Equipment ownership/max-level interpretation from the village export, especially Epic equipment whose export level may not mean it is owned.
6. Recovery when the Build list or a confirmation dialog fails to appear.
7. Builder Base upgrade behavior with a missing/ambiguous builder count or a busy Star Laboratory.

No code changes to the upgrade engine are justified from this comparison yet. The main missing CoC_Bot convenience is a global random-vs-priority switch; COCFARM's ordered category and allow-list system should remain intact.


## Sixth-pass deep dive: scheduler, recovery, OCR dependencies and unattended operation

### COCFARM scheduler

COCFARM's schedule is richer than CoC_Bot's periodic check loop:
- Selects local active hours (0-23), with optional randomized start/stop offsets at the edges of active-hour windows.
- Chooses a daily attack limit randomly within a configured minimum/maximum range.
- Supports random breaks after a range of attack counts and random break durations.
- Supports a day off at a configured frequency and optional daily summaries.
- Supports "Close between upgrades": once relevant builders/labs are busy, it can close the game and schedule a one-off Windows Task Scheduler job to reopen COCFARM after the earliest upgrade finishes.
- Supports "Pause when idle" without closing the COCFARM process; it stops attacks and waits for upgrade completion.
- In Auto mode it can move between Home Village and Builder Base based on selected storage fullness.

CoC_Bot's template config exposes a simple CHECK_INTERVAL and task loop, but no equivalent rich active-hour/day-off/random daily attack schedule was found in the inspected source. COCFARM is a clear advantage here.

### Recovery and failure containment

COCFARM's main loop distinguishes known non-recoverable states from recoverable round failures:
- Game refresh/update events return to searching rather than being treated as generic crashes.
- A blocked attack is handled by closing the game, waiting a randomized 3-5 minute window and reopening.
- A Supercell maintenance break is waited out, with periodic checks and a maximum wait.
- Not-logged-in, wrong-account and game-not-installed conditions stop rather than blindly retry.
- Other round failures save the error screenshot, write diagnostics, notify if configured, restart the game and then restart the emulator if the game restart fails and a reopen callback is available.
- Consecutive failures are capped; the bot stops after the configured internal threshold rather than looping forever.
- Error screenshots are retained in a bounded set per account/farm.
- Pause/stop checkpoints are designed to act between safe actions, not in the middle of a battle.

This is a substantial resilience advantage. Still validate recovery on deliberately induced safe failures (ADB disconnect, game process closed, maintenance screen simulation, missing template) rather than forcing disruptive real-game failures.

### OCR and CV dependency correction

The OCR stack in COCFARM has three distinct local mechanisms:
1. OpenCV template matching and color/shape analysis for buttons, cards, troop bars, spell icons, deploy boundaries and other visual UI.
2. Custom glyph segmentation/classification in `farmbot/text.py` for numeric values such as loot, troop counts, timers and Clan Castle room capacities. Digits are learned from local screenshots via the font/glyph workflow.
3. Windows built-in OCR via `farmbot/ocr.ps1` and `farmbot/ocr_lines.ps1` for actual words/text and line positions, used by player-name recognition, game-update dialogs, Build-list row names, equipment names, Clan Games challenge names and other text-based UI paths.

Therefore it is not accurate to say COCFARM recognizes all text only through CV. It uses CV plus local glyph OCR plus the Windows OCR engine. None of these require Groq, Llama, a remote AI OCR API or uploading screenshots to a third-party model. The Windows OCR scripts require Windows 10 or later and depend on available Windows OCR language packs. The README's English game-language recommendation remains relevant because UI labels and templates are English-centric.

### Unattended-operation tradeoffs

- COCFARM's "Close game when not playing" closes the Clash of Clans app, not the emulator VM.
- Its scheduled wake-up is Windows Task Scheduler based and uses an interactive logged-in session; it does not set WakeToRun, so it should not be described as waking a sleeping/off PC.
- CoC_Bot's DISABLE_DEVICE_SLEEP attempts to keep the host awake; COCFARM has no equivalent setting found. This is an optional convenience gap, not a farming-feature gap.
- CoC_Bot's SUSPEND_EMULATOR_ON_IDLE suspends emulator processes; COCFARM's offline-break behavior is not equivalent.
- For the intended personal Windows PC, these two power-management features can be considered optional future additions. Do not add them without testing their effects on ADB, emulator integrity and Windows power behavior.

### Updated migration assessment

The source audit now supports choosing COCFARM as the base with high confidence for the target Windows desktop workflow. It has the more extensive farming/clan/upgrade features, more sophisticated scheduling and richer failure recovery. CoC_Bot-only features still worth deciding on are:
- Independent Builder Base attack on/off switch.
- Optional exclusion of donated Clan Castle troop cards during attacks.
- Optional troop-bar slot range.
- Optional global priority-vs-random upgrade selection.
- Optional host-awake and emulator-suspend power management.
These should be implemented as small native COCFARM config/UI additions only if desired, not by importing CoC_Bot's dashboard/API or rewriting COCFARM subsystems.



## Seventh-pass deep dive: GUI, profiles, local data, updater and user-facing operation

### Desktop GUI and configuration model

COCFARM's GUI is a native PySide6 / Qt 6 desktop application with Fluent Widgets. The pages cover Dashboard, Home Village, Builder Base, Wars & Raids, When to Play, Like a Person, History, Farms/accounts and Advanced. Settings are TOML-backed, validated as they are edited, saved automatically once valid, and picked up by a running bot at its next safe step. It has light/dark/follow-Windows themes, keyboard shortcuts, onboarding and a status/problem explanation layer.

The GUI is not a web dashboard or local HTTP service. This matches the user's preference for a personal desktop-only application and avoids importing CoC_Bot's web server/API architecture.

### Multi-account profile handling

Profiles are account-specific and stored as:
- `profiles/<player-name>.toml`: the account's settings.
- `profiles/<player-name>.png`: a cropped/masked player-name image used to distinguish accounts visually.
- `profiles/<player-name>.village.json`: the account's Data Export used to know its Town Hall, unlocks, levels and ongoing upgrades.

PC-wide settings (emulator, screen regions, notifications, profile list and selected app theme/update settings) remain in the main `farmbot.toml`. Each farm has its own emulator configuration, history and error screenshots under `instances/<n>/`; account profiles and templates are shared across farms. The GUI supports starring a default profile, copying settings, renaming and deleting profiles. It blocks rename/delete while a farm is actively using that profile. Removing a farm preserves its folder as `removed-<n>` rather than immediately deleting its history.

Account recognition uses the player's visible name image and Windows OCR; uncertain matches are not silently switched. If OCR cannot read a name, a fallback Account N profile is created and can be renamed later. This is a sensible fail-closed design, but verify two accounts with similar names and an OCR-unreadable name before relying on unattended multi-account operation.

### Local data and privacy boundaries

The inspected source stores settings, attack history (CSV), error screenshots, account name pictures, and village exports locally beside the app. The game Data Export is read locally from a file copied by the user; no cloud account is required for it. The normal farming/vision path does not upload screenshots or village exports to an AI/OCR service.

The only clear optional outbound services in this area are GitHub release/update checks and Discord webhooks. Discord is disabled unless the user enters a webhook URL. Telegram notifications from CoC_Bot are out of scope. COCFARM's existing optional Discord webhook is separate; do not add Telegram, and leave the Discord integration unchanged until the user explicitly decides whether to use it. Treat `farmbot.toml`, profile TOMLs, village JSON, screenshots and logs as private user data: never commit them to the public source repository or include them in bug reports without reviewing/redacting them. A Discord webhook URL, if ever configured, is a credential and must not be shared.

### Important migration-specific updater setting

The current COCFARM default is `bot.update_repo = "BilinP/COCFARM"`, with `check_updates = true`. If the migrated application is customized in `Syhung2k7dev/CoC_Bot` (or a new repository) but keeps this default, the built app will continue checking and downloading the upstream COCFARM release, not the user's customized build. That could replace the user's customized program with an upstream release and effectively discard the migration in the installed copy.

Before publishing a customized release, change the default update repository to the user's chosen repository and verify its release asset naming/checksum. Until that repository publishes compatible releases, turn automatic update checks off in the migrated build. Do not point the updater at a repository that does not yet contain compatible COCFARM release assets.

### Updater implementation and limits

The updater:
- Checks GitHub releases using ETags and rate-limit backoff.
- Downloads the Windows zip with resumable chunks.
- Checks the asset's declared size and SHA-256 digest when GitHub provides one.
- Rejects archives whose paths escape the expected `COCFARM/` root or contain parent traversal, absolute paths or colon characters, and requires `COCFARM/COCFARM.exe`.
- Installs with a separate PowerShell process after the app exits, retains user data folders, and attempts rollback if moving the new program files fails.
- Does not self-update when run from source; source users should update via Git.

The checksum is not a publisher signature. It proves the downloaded bytes match the digest returned by GitHub's release metadata, but it does not protect against compromise of the repository, release account or GitHub publishing credentials. Keep the updater disabled until the customized repository/release flow is configured. For the first migrated releases, publish manually and verify the release artifact/checksum independently.

### GUI and usability migration conclusion

No major GUI feature from CoC_Bot needs to be transplanted. COCFARM already has a native desktop interface, profile management, per-account settings, history, onboarding and emulator management. The only GUI work justified so far is exposing the small accepted control gaps (especially Builder Base attack enable/disable) and removing/hiding unused Discord settings only if doing so does not make future upstream merges harder. Prefer leaving the unused Discord integration dormant rather than deleting large chunks of upstream code.



## Eighth-pass deep dive: build pipeline, dependency supply chain, tests and release security

### Build and packaging

COCFARM is packaged as a Windows PyInstaller `--onedir` application, then zipped as `COCFARM-windows.zip`. The build bundles the GUI, OpenCV, assets, emulator helpers, local OCR PowerShell scripts, profiles shipped as examples, third-party notices and license texts. The runtime folder is intentionally portable: settings, account profiles, history, screenshots and logs live beside it. The build script refuses to overwrite a `dist/COCFARM` folder that already contains farm data, which helps prevent accidental loss during a rebuild.

The project supports Python 3.11+ in `pyproject.toml`; CI currently builds on Python 3.12 and Windows. Dependencies are declared as minimum versions rather than exact pins, and there is no dependency lockfile or hash-locked requirements set. This makes fresh builds less reproducible: a later compatible dependency release may change behavior or packaging.

### CI workflow finding: excessive write permission during PR builds

The only workflow, `.github/workflows/windows-exe.yml`, sets workflow-wide `permissions: contents: write`. The same job checks out the branch/PR source, installs dependencies, executes `packaging/build.py`, and runs the built executable's self-test. That means untrusted code from a same-repository pull request can run in a job whose token is configured for write access; checkout also normally persists its Git credentials unless disabled. GitHub restricts tokens for fork-originated PRs, but same-repository PRs are a different trust boundary.

Before using this workflow in the user's repository, split it:
- Build/test jobs should use `permissions: contents: read` (or no write permission) and `actions/checkout` with `persist-credentials: false`.
- A separate release-publish job should run only for trusted version tags or a manually approved release path and receive `contents: write`.
- Pin third-party Actions to reviewed full commit SHAs rather than movable version tags, and review updates deliberately.
- Never run a release-publishing job against untrusted pull-request code.

This is a concrete CI hardening item, not evidence that the current local bot leaks user data.

### Test coverage actually present in main

The recursive tree of the audited main commit contains no committed `tests/` directory. Although `pyproject.toml` configures pytest and the development dependencies include pytest/pytest-xdist, the current Windows workflow does not run pytest. It builds the executable and invokes `--self-test`, which opens every GUI page, checks that required shipped templates exist, and imports OpenCV.

That self-test is useful for packaging and missing-resource regressions, but it does not exercise attack deployment, donation, OCR recognition, upgrade decisions, scheduler edge cases, updater rollback, multi-instance claims or profile switching. Several open PRs add synthetic tests, but they are not present in main. A migration should establish a real portable test suite before changing core behavior.

### Release integrity and trust

The updater validates the downloaded asset's declared size and SHA-256 digest when GitHub's release metadata supplies them. It does not verify a publisher signature or a signed provenance attestation. The current release having a SHA-256 digest is good, but the digest is delivered by the same GitHub repository/release trust domain as the asset. A compromised repository maintainer account or release pipeline could replace both.

The Windows executable is not Authenticode-signed in the inspected workflow. README therefore warns that Windows may show an unknown publisher. This is a user-trust/reputation limitation, not by itself proof of malicious code. For the user's own releases, consider signing only if a trusted code-signing certificate is available; do not download third-party certificates or disable Windows security checks to suppress warnings.

### Licensing and redistribution

The audited COCFARM main declares GPL-3.0-or-later and includes third-party notices and license texts for its packaged dependencies. CoC_Bot's previous MIT license does not override the license of the imported COCFARM code. If the user distributes a modified executable/source bundle, retain the upstream copyright/license notices, provide the corresponding GPL source and comply with GPL-3.0-or-later obligations. Private local modification is a different situation from public redistribution; this should be revisited before publishing a binary or sharing it with others.

### Data and diagnostic handling

COCFARM writes normal logs, crash traces, per-account history and screenshots locally. The diagnostic bundle can include platform/Python/game/emulator facts and log context; review the exact report before posting it publicly. Account names, profile images, village exports, emulator serials/ports, paths and webhook URLs should be treated as potentially sensitive. Add a safe redaction pass before any bug-report export is attached to a public GitHub issue.

### Final source-audit conclusion

The remaining code-reading audit is complete enough to start implementation planning. COCFARM is still the right base, but the migration must not simply copy its tree and publish it unchanged. The minimum pre-release engineering tasks are:
1. Change or disable the upstream update repository default before the customized build can self-update.
2. Add the independent Builder Base attack enable/disable control and its tests.
3. Review and selectively integrate PR #38 and #40 for attack-bar/Builder Base deployment correctness.
4. Add focused tests for donations, spells, Hero Walk, profiles, config migration and updater extraction/rollback.
5. Harden the GitHub Actions permissions and release job separation.
6. Keep user settings/profiles/screenshots/logs out of Git and add diagnostic redaction.
7. Preserve GPL-3.0-or-later and third-party notices in any distributed derivative.

The audit branch still contains documentation only. No COCFARM source tree has been imported, no CoC_Bot source code has been rewritten, and no emulator/live-game tests have been run.


## Ninth-pass deep dive: persistence paths and exact Builder Base control insertion points

### Settings and GUI save lifecycle

- The settings model is a hierarchy of dataclasses in `farmbot/config.py`; `load_config()` merges TOML into known fields, applies migrations for removed/renamed settings, then calls `Config.validate()`. Unknown settings are rejected rather than silently accepted.
- The GUI maps controls to dotted config paths, validates the collected form on every change, and uses a single-shot 400 ms timer to autosave. Invalid values stop the timer, so the GUI does not persist a partially invalid configuration. Lazy-built pages retain pending values so settings on unopened tabs are not lost during a save.
- `save_config()` preserves comments/layout by editing changed TOML lines where possible, and falls back to a full TOML rewrite when that cannot be done. The final write is a direct `Path.write_text()`, not a temp-file + atomic replace; no cross-process file lock is visible in this module. This is a hardening candidate for crash/power-loss safety, not proof of an existing data-loss incident.
- The GUI's current Builder Base page already has an **Attacking** tab, with controls for corner, hero, troop timing, abilities, speed and second-base behavior. A global enable/disable switch belongs at the top of this tab, rather than in the Home Village search settings.

### Account, farm and history persistence

- Account profile files are saved as TOML, with a companion player-name picture and optional village export. Profile names are sanitized for Windows-invalid filename characters; collisions are handled case-insensitively. Account switching uses image similarity thresholds and deliberately refuses to switch when the match is ambiguous.
- Each emulator farm has its own `farmbot.toml`, attack CSV, and error-screen folder. The list of farms selected to start is stored separately in `instances/picked.json`. Account profiles and templates are shared. Removing a farm preserves its folder under a `removed-<n>` name.
- Attack history is append-only CSV, with a header created for a new file. Readers skip malformed rows, and the GUI calculates daily totals and per-hour loot from the records. No explicit file lock is present in the history writer; per-farm history separation reduces ordinary contention, but shared/custom history paths should be tested.
- Profile TOML, profile images, village exports, `picked.json`, storage snapshots and logs are runtime data. They must remain outside Git and must not be copied into release artifacts or public diagnostics without deliberate redaction.

### Updater data-preservation check

The installer preserves a fixed set of root-level names (settings, history, logs, screenshots, update state and templates) and overlays files present in the new release. The current profile and multi-farm directories are runtime-created beside the application and are not part of the packaged program tree. Keep that separation explicit: if a future release ever ships root-level `profiles/` or `instances/`, add them to the installer's preservation rules and test an update with existing accounts/farms before publishing. The customized build must also replace or disable the upstream `BilinP/COCFARM` update repository default before self-update is enabled.

### Exact implementation seam: independent Builder Base attack toggle

The smallest native parity change is `builder.attack_enabled`:
1. Add a boolean field to `BuilderConfig` in `farmbot/config.py`, defaulting to `true` to preserve current behavior.
2. Add it to `farmbot.example.toml` and the GUI's existing Builder Base → Attacking tab, above the deployment controls. Use the existing typed binding/validation path; no new API or central task-exclusion service is needed.
3. In `Bot.builder_cycle()`, keep the existing navigation, account check, resource collection, Clock Tower/cart work, upgrades and walls. After those maintenance jobs, skip only the battle path when the switch is off; run the existing no-battle cleanup so selected objects/zoom are restored, and do not increment attack counters or write a fake attack record.
4. Confirm the scheduler's return-value and checkpoint semantics before choosing the skip return path. Add tests for both enabled (identical current behavior) and disabled (maintenance still runs, no battle starts, counters/history unchanged), including Clan Games behavior if a Builder Base challenge is active.
5. Leave Home Village attack behavior unchanged. Do not add donated-troop exclusion, slot-range limits, priority randomization, emulator suspension or host-awake behavior in this same patch; those remain separate optional decisions.

### Updated status

The GUI, settings model, profile/farm storage, attack history and updater code-reading pass is complete. No COCFARM source code has been imported or modified by this audit update, and no emulator/live-game validation has been performed. The next implementation step is to build the migration branch's regression-test scaffold and implement the isolated Builder Base attack toggle only after checking scheduler semantics and the active Clan Games path.
