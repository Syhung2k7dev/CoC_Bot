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
