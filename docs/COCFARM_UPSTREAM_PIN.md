# COCFARM upstream source pin

This branch uses COCFARM as its sole runtime base.

- Upstream repository: https://github.com/BilinP/COCFARM
- Imported upstream commit: 46ddfa032e81baea8a6c62824468bea7c19ee413
- Commit URL: https://github.com/BilinP/COCFARM/commit/46ddfa032e81baea8a6c62824468bea7c19ee413
- License: GNU GPL version 3 or later; see the root LICENSE.
- Third-party notices: see THIRD_PARTY_NOTICES.md and licenses/.

The source snapshot is copied into this repository, not linked as a submodule.
Preserve upstream copyright and license notices. Review future upstream
updates before integrating them; do not blindly overwrite local changes.

## Migration decisions

- Local PC execution only.
- No Web Dashboard, Telegram notifications, or iPhone Shortcut.
- No external AI/OCR service; perception remains local.
- No Dry Run mode.
- Instant upgrade items may be used automatically only when eligibility
  and a valid target are positively identified.
- Never spend gems or paid currency automatically.
- Boost/timer automation remains optional and user-controlled.
