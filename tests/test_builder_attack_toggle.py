from farmbot.config import BuilderConfig, Config, dump_config, load_config
from farmbot.form import BY_PATH


def test_builder_attacks_remain_enabled_by_default():
    assert BuilderConfig().attack_enabled is True


def test_builder_attack_toggle_loads_and_round_trips(tmp_path):
    source = tmp_path / "farmbot.toml"
    source.write_text("[builder]\nattack_enabled = false\n", encoding="utf-8")

    config = load_config(source)
    assert config.builder.attack_enabled is False

    saved = tmp_path / "roundtrip.toml"
    saved.write_text(dump_config(config), encoding="utf-8")
    assert load_config(saved).builder.attack_enabled is False


def test_builder_attack_toggle_is_exposed_to_the_settings_form():
    assert BY_PATH["builder.attack_enabled"].kind == "bool"


def test_custom_build_does_not_auto_update_from_upstream():
    config = Config()
    assert config.bot.update_repo == ""
    assert config.bot.check_updates is False



def test_existing_upstream_update_settings_are_ignored(tmp_path):
    source = tmp_path / "old-farmbot.toml"
    source.write_text(
        '[bot]\nupdate_repo = "BilinP/COCFARM"\ncheck_updates = true\n',
        encoding="utf-8",
    )

    config = load_config(source)
    assert config.bot.update_repo == ""
    assert config.bot.check_updates is False
