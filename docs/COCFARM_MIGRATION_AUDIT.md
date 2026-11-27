# COCFARM migration audit

Status: initial source-level audit; runtime validation and full module-by-module comparison remain in progress.

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
| Multiple emulator instances / accounts | Present (`instances.py`, `accounts.py`) | Present | Compare lifecycle and failure recovery in the next audit pass. |
| Scheduling / breaks | Present (`ScheduleConfig`, bot scheduler) | Not yet fully verified | Inspect CoC_Bot scheduling semantics before marking parity. |
| Per-task controls | Separate settings across `Config` groups | Central `Task_Handler` exclusion list | COCFARM already has granular category toggles; assess whether a unified exclusion UI is still useful. |
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

Therefore the core idea of independently enabling/disabling major task groups is already present in COCFARM. What is not yet confirmed is whether every CoC_Bot exclusion has a direct COCFARM GUI equivalent, especially attack-only controls and a single centralized exclusion list. Do not port CoC_Bot's remote API machinery just to reproduce this; use native COCFARM settings.

## Initial engineering / security observations

- COCFARM's `farmbot/update.py` checks the release asset size and, when GitHub supplies it, SHA-256. The inspected latest release does supply a SHA-256 digest.
- `unpack()` checks archive paths are under the expected `COCFARM/` root and rejects parent traversal, absolute paths, and colon-containing paths before extraction.
- The updater does not verify a publisher signature; the checksum is obtained from GitHub's release metadata. Treat GitHub account/repository compromise as outside that checksum's protection.
- COCFARM parses TOML with Python's `tomllib`, uses JSON/CSV for local state, and controls emulators through ADB/subprocesses.
- The COCFARM tree has no `tests/` directory in the inspected main commit, although `pyproject.toml` configures pytest and CI builds the Windows executable and runs its `--self-test`. This is not a substitute for a comprehensive unit/integration suite.
- Large modules deserve maintainability review: `farmbot/gui.py` (~406 KB), `farmbot/bot.py` (~136 KB), and `farmbot/tasks/attack.py` (~107 KB). CoC_Bot also has large modules (`src/utils.py`, `src/upgrader.py`), so code size alone is not a reason to transplant its architecture.
- Licensing differs: COCFARM is GPL-3.0-or-later; CoC_Bot is MIT. Any combined distributed derivative must comply with GPL-3.0-or-later and preserve applicable copyright/license notices.

## Next audit pass

1. Finish task-by-task parity for every CoC_Bot exclusion and every COCFARM settings control.
2. Inspect attack, upgrade, OCR, device/emulator, account/profile, scheduler, recovery, updater and GUI paths in detail.
3. Review COCFARM open issues and recent commit history for known regressions.
4. Add focused automated tests for configuration, OCR parsing, task selection, persistence, emulator lifecycle and update archive validation.
5. Only then decide the minimal code to port from CoC_Bot and begin integration on a separate migration branch. Do not edit the upstream COCFARM repository.
