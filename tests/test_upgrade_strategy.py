from farmbot.config import Config, load_config
from farmbot.townhall import Village
from farmbot import upgradable


def test_upgrade_strategy_defaults_to_rush_and_accepts_maxer(tmp_path):
    assert Config().upgrade.strategy == "rush"
    path = tmp_path / "farmbot.toml"
    path.write_text('[upgrade]\nstrategy = "maxer"\n', encoding="utf-8")
    assert load_config(path).upgrade.strategy == "maxer"


def test_unknown_upgrade_strategy_is_rejected(tmp_path):
    path = tmp_path / "farmbot.toml"
    path.write_text('[upgrade]\nstrategy = "instant"\n', encoding="utf-8")
    try:
        load_config(path)
    except ValueError as exc:
        assert "upgrade.strategy" in str(exc)
    else:
        raise AssertionError("invalid strategy was accepted")


def test_maxer_requires_a_fresh_survey_for_each_enabled_category(tmp_path):
    village = Village(town_hall=18)
    path = tmp_path / "account.upgradable.json"
    upgradable.save(path, "buildings", village, set(), "2026-11-28")
    assert not upgradable.maxed_for_town_hall(path, village, 1_000, ("buildings", "research"))
    upgradable.save(path, "research", village, set(), "2026-11-28")
    assert upgradable.maxed_for_town_hall(path, village, 1_000, ("buildings", "research"))


def test_maxer_waits_for_every_upgradeable_building(tmp_path):
    village = Village(town_hall=18)
    path = tmp_path / "account.upgradable.json"
    upgradable.save(path, "buildings", village, {"Cannon"}, "2026-11-28")
    upgradable.save(path, "research", village, set(), "2026-11-28")
    assert not upgradable.maxed_for_town_hall(path, village, 1_000, ("buildings", "research"))


def test_maxer_does_not_block_on_town_hall_row_itself(tmp_path):
    village = Village(town_hall=18)
    path = tmp_path / "account.upgradable.json"
    upgradable.save(path, "buildings", village, {"Town Hall"}, "2026-11-28")
    upgradable.save(path, "research", village, set(), "2026-11-28")
    assert upgradable.maxed_for_town_hall(path, village, 1_000, ("buildings", "research"))


def test_maxer_waits_for_upgrades_still_in_progress(tmp_path):
    village = Village(town_hall=18, finishing={1: (2_000,)})
    path = tmp_path / "account.upgradable.json"
    upgradable.save(path, "buildings", village, set(), "2026-11-28")
    upgradable.save(path, "research", village, set(), "2026-11-28")
    assert not upgradable.maxed_for_town_hall(path, village, 1_000, ("buildings", "research"))
