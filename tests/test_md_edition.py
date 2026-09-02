"""Millennium Dawn editions: main release vs beta test mod."""
from __future__ import annotations

import pytest

from core.md_edition import (
    BETA,
    MAIN,
    active_edition,
    edition,
    edition_context,
    edition_of_root,
    edition_of_roots,
    roots_with_md_root,
    set_active_edition,
)
from core.mod_scaffold import MD_DEPENDENCY, DEFAULT_SUPPORTED_VERSION, scaffold_defaults, scaffold_submod
from core.reward_presets import (
    build_reward_item_lines,
    get_reward_preset,
    preset_available,
    reward_preset_groups,
    validate_reward_item,
)
from core.reward_script import parse_reward_lines
from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict
from core.types import CompletionReward, RewardItem
from core.exporters import export_completion_reward_lines, export_project_files


@pytest.fixture(autouse=True)
def _reset_active_edition():
    set_active_edition("main")
    yield
    set_active_edition("main")


# ----- lookup -----------------------------------------------------------------

def test_edition_lookup_falls_back_to_main():
    assert edition("beta") is BETA
    assert edition("BETA ") is BETA
    assert edition("main") is MAIN
    assert edition("") is MAIN
    assert edition(None) is MAIN
    assert edition("something-else") is MAIN


def test_editions_differ_where_md_does():
    assert MAIN.workshop_id != BETA.workshop_id
    assert MAIN.dependency == "Millennium Dawn: A Modern Day Mod"
    assert BETA.dependency == "Millennium Dawn: A Beta Test Mod"
    assert MAIN.supported_version == "1.17.*" and BETA.supported_version == "1.19.*"
    assert MAIN.party_popularity_effect == "add_relative_party_popularity"
    assert BETA.party_popularity_effect == "change_relative_party_popularity"
    assert MAIN.has_radicalization and not BETA.has_radicalization


# ----- detection ---------------------------------------------------------------

def _md_folder(tmp_path, folder, descriptor, with_ideologies=True):
    d = tmp_path / folder
    d.mkdir(parents=True)
    (d / "descriptor.mod").write_text(descriptor, encoding="utf-8")
    if with_ideologies:
        (d / "common" / "ideologies").mkdir(parents=True)
    return str(d)


def test_detect_by_workshop_folder_name(tmp_path):
    main = _md_folder(tmp_path, "2777392649", 'name="whatever"\n', with_ideologies=False)
    beta = _md_folder(tmp_path, "3374271790", 'name="whatever"\n', with_ideologies=False)
    assert edition_of_root(main) is MAIN
    assert edition_of_root(beta) is BETA


def test_detect_by_remote_file_id(tmp_path):
    beta = _md_folder(tmp_path, "md_beta_local", 'name="MD local copy"\nremote_file_id="3374271790"\n')
    assert edition_of_root(beta) is BETA


def test_detect_by_descriptor_name(tmp_path):
    main = _md_folder(tmp_path, "md_fork", 'name="Millennium Dawn: A Modern Day Mod"\n')
    beta = _md_folder(tmp_path, "md_beta_fork", 'name="Millennium Dawn: A Beta Test Mod"\n')
    assert edition_of_root(main) is MAIN
    assert edition_of_root(beta) is BETA


def test_submods_are_not_editions(tmp_path):
    # Depends on MD → a submod, even if it's named "Millennium Dawn: …"
    sub = _md_folder(tmp_path, "md_chile",
                     'name="Millennium Dawn: Chile"\ndependencies={\n\t"Millennium Dawn: A Modern Day Mod"\n}\n')
    assert edition_of_root(sub) is None
    # Named like MD but ships no ideology definitions → not a base mod
    sub2 = _md_folder(tmp_path, "md_argentina", 'name="Millennium Dawn: Argentina Expanded"\n',
                      with_ideologies=False)
    assert edition_of_root(sub2) is None
    other = _md_folder(tmp_path, "kr", 'name="Kaiserreich"\n')
    assert edition_of_root(other) is None
    assert edition_of_root(str(tmp_path / "missing")) is None
    assert edition_of_root("") is None


def test_edition_of_roots_last_md_wins(tmp_path):
    game = str(tmp_path / "Hearts of Iron IV")
    main = _md_folder(tmp_path, "2777392649", 'name="MD"\n', with_ideologies=False)
    beta = _md_folder(tmp_path, "3374271790", 'name="MD beta"\n', with_ideologies=False)
    sub = _md_folder(tmp_path, "md_sub", 'name="Sub"\ndependencies={ "Millennium Dawn: A Modern Day Mod" }\n',
                     with_ideologies=False)
    assert edition_of_roots([game, main, sub]) is MAIN
    assert edition_of_roots([game, beta, sub]) is BETA
    assert edition_of_roots([game, main, beta]) is BETA
    assert edition_of_roots([game, sub]) is None
    assert edition_of_roots([]) is None


def test_roots_with_md_root_swaps_in_place(tmp_path):
    game = str(tmp_path / "Hearts of Iron IV")
    main = _md_folder(tmp_path, "2777392649", 'name="MD"\n', with_ideologies=False)
    beta = _md_folder(tmp_path, "3374271790", 'name="MD beta"\n', with_ideologies=False)
    sub = str(tmp_path / "md_sub")
    assert roots_with_md_root([game, main, sub], beta) == [game, beta, sub]
    assert roots_with_md_root([game, beta, sub], main) == [game, main, sub]
    # both present → collapse onto one, at the first MD position
    assert roots_with_md_root([game, main, beta, sub], beta) == [game, beta, sub]
    # no MD yet → right after the game
    assert roots_with_md_root([game, sub], beta) == [game, beta, sub]
    assert roots_with_md_root([], beta) == [beta]
    # already the target → unchanged
    assert roots_with_md_root([game, beta, sub], beta) == [game, beta, sub]


# ----- active edition context ---------------------------------------------------

def test_active_edition_context_restores():
    assert active_edition() is MAIN
    with edition_context("beta"):
        assert active_edition() is BETA
        with edition_context(MAIN):
            assert active_edition() is MAIN
        assert active_edition() is BETA
    assert active_edition() is MAIN


# ----- reward presets follow the edition ----------------------------------------

def test_party_popularity_helper_follows_edition():
    item = {"kind": "relative_party_popularity", "enabled": True,
            "params": {"partyIndex": 14, "popularity": 0.05, "outlook": 0}}
    main_lines = build_reward_item_lines(item)
    assert main_lines[-1] == "add_relative_party_popularity = yes"
    with edition_context("beta"):
        beta_lines = build_reward_item_lines(item)
    assert beta_lines[-1] == "change_relative_party_popularity = yes"
    assert beta_lines[:-1] == main_lines[:-1]   # inputs identical


def test_radicalization_hidden_and_flagged_in_beta():
    rad = get_reward_preset("radicalization")
    assert preset_available(rad, MAIN)
    assert not preset_available(rad, BETA)
    main_kinds = {p.kind for _g, ps in reward_preset_groups(MAIN) for p in ps}
    beta_kinds = {p.kind for _g, ps in reward_preset_groups(BETA) for p in ps}
    assert "radicalization" in main_kinds
    assert main_kinds - beta_kinds == {"radicalization"}
    item = {"kind": "radicalization", "enabled": True, "params": {"amount": -5}}
    assert validate_reward_item(item) == []
    with edition_context("beta"):
        issues = validate_reward_item(item)
    assert issues and "Millennium Dawn Beta" in issues[0]


def test_structure_accepts_either_editions_helper_name():
    """Raw script written for either MD structures into the same preset, and
    re-exports with the ACTIVE edition's helper."""
    beta_raw = [
        "set_temp_variable = { party_index = 14 }",
        "set_temp_variable = { party_popularity_increase = 0.05 }",
        "set_temp_variable = { temp_outlook_increase = 0 }",
        "change_relative_party_popularity = yes",
    ]
    main_raw = beta_raw[:-1] + ["add_relative_party_popularity = yes"]
    for raw in (beta_raw, main_raw):
        items, leftover = parse_reward_lines(raw)
        assert leftover == []
        assert len(items) == 1 and items[0]["kind"] == "relative_party_popularity"
        assert items[0]["params"] == {"partyIndex": "14", "popularity": "0.05", "outlook": "0"}
        # Re-emits with the ACTIVE edition's name regardless of the source spelling.
        assert build_reward_item_lines(items[0])[-1] == "add_relative_party_popularity = yes"
        with edition_context("beta"):
            assert build_reward_item_lines(items[0])[-1] == "change_relative_party_popularity = yes"
    # Under the beta edition the main-spelled source still structures.
    with edition_context("beta"):
        items, leftover = parse_reward_lines(main_raw)
    assert leftover == [] and items[0]["kind"] == "relative_party_popularity"


def test_export_uses_projects_edition_not_ui_state():
    project = make_sample_project()
    project.focuses[0].completionReward = CompletionReward(items=[
        RewardItem(kind="relative_party_popularity",
                   params={"partyIndex": 1, "popularity": 0.02, "outlook": 0}),
    ])
    project.mdEdition = "beta"
    set_active_edition("main")                      # UI shows main…
    text = "\n".join(f.content for f in export_project_files(project))
    assert "change_relative_party_popularity = yes" in text   # …export targets beta
    assert "add_relative_party_popularity" not in text
    assert active_edition() is MAIN                 # context restored

    project.mdEdition = "main"
    text = "\n".join(f.content for f in export_project_files(project))
    assert "add_relative_party_popularity = yes" in text


def test_completion_reward_lines_default_main():
    reward = CompletionReward(items=[
        RewardItem(kind="relative_party_popularity",
                   params={"partyIndex": 1, "popularity": 0.02, "outlook": 0})])
    assert "add_relative_party_popularity = yes" in "\n".join(export_completion_reward_lines(reward))


# ----- project field ------------------------------------------------------------

def test_md_edition_round_trips_and_defaults():
    project = make_sample_project()
    assert project.mdEdition == "main"
    project.mdEdition = "beta"
    d = project_to_dict(project)
    assert d["mdEdition"] == "beta"
    assert project_from_dict(d).mdEdition == "beta"
    d.pop("mdEdition")                              # a project saved by an older build
    assert project_from_dict(d).mdEdition == "main"
    d["mdEdition"] = None
    assert project_from_dict(d).mdEdition == "main"


# ----- scaffold defaults --------------------------------------------------------

def test_scaffold_defaults_per_edition(tmp_path):
    assert scaffold_defaults("main") == {"dependencies": [MD_DEPENDENCY],
                                         "supported_version": DEFAULT_SUPPORTED_VERSION}
    beta = scaffold_defaults("beta")
    assert beta == {"dependencies": ["Millennium Dawn: A Beta Test Mod"],
                    "supported_version": "1.19.*"}
    scaffold_submod(str(tmp_path), "md_chile_beta", "MD Beta: Chile", **beta)
    inner = (tmp_path / "md_chile_beta" / "descriptor.mod").read_text(encoding="utf-8")
    assert '"Millennium Dawn: A Beta Test Mod"' in inner
    assert 'supported_version="1.19.*"' in inner
    assert "A Modern Day Mod" not in inner


# ----- converting an existing project ---------------------------------------------

def test_retarget_mod_meta_swaps_only_edition_facts():
    from core.md_edition import retarget_mod_meta
    meta = {"name": "Chile", "tags": ["Gameplay"],
            "dependencies": [MD_DEPENDENCY, "Some Other Mod"], "supported_version": "1.17.*"}
    out = retarget_mod_meta(meta, "beta")
    assert out["dependencies"] == ["Millennium Dawn: A Beta Test Mod", "Some Other Mod"]
    assert out["supported_version"] == "1.19.*"
    assert out["name"] == "Chile" and meta["dependencies"][0] == MD_DEPENDENCY  # input untouched
    # back again
    back = retarget_mod_meta(out, "main")
    assert back["dependencies"] == [MD_DEPENDENCY, "Some Other Mod"]
    assert back["supported_version"] == "1.17.*"
    # hand-typed version and custom-only deps are respected; blank version filled
    custom = retarget_mod_meta({"dependencies": ["Only Mine"], "supported_version": "1.18.2"}, "beta")
    assert custom == {"dependencies": ["Only Mine"], "supported_version": "1.18.2"}
    assert retarget_mod_meta({}, "beta")["supported_version"] == "1.19.*"
    assert "dependencies" not in retarget_mod_meta({}, "beta")


def test_retarget_descriptor_rewrites_both_files(tmp_path):
    from core.mod_scaffold import retarget_descriptor
    scaffold_submod(str(tmp_path), "md_chile", "MD: Chile")      # main-branch descriptors
    changed = retarget_descriptor(tmp_path / "md_chile", "beta")
    assert len(changed) == 2
    inner = (tmp_path / "md_chile" / "descriptor.mod").read_text(encoding="utf-8")
    outer = (tmp_path / "md_chile.mod").read_text(encoding="utf-8")
    for text in (inner, outer):
        assert '"Millennium Dawn: A Beta Test Mod"' in text
        assert 'supported_version="1.19.*"' in text
        assert MD_DEPENDENCY not in text
    assert 'path="' in outer                       # outer keeps its path line
    # already targeting beta → no-op
    assert retarget_descriptor(tmp_path / "md_chile", "beta") == []
    # missing folder → no-op, no error
    assert retarget_descriptor(tmp_path / "nope", "beta") == []


def test_retarget_descriptor_keeps_custom_version(tmp_path):
    from core.mod_scaffold import retarget_descriptor
    scaffold_submod(str(tmp_path), "md_x", "X", supported_version="1.18.7")
    retarget_descriptor(tmp_path / "md_x", "beta")
    inner = (tmp_path / "md_x" / "descriptor.mod").read_text(encoding="utf-8")
    assert 'supported_version="1.18.7"' in inner
    assert '"Millennium Dawn: A Beta Test Mod"' in inner


def test_foreign_helpers_per_edition():
    from core.md_edition import foreign_helpers
    assert set(foreign_helpers(MAIN)) == {"change_relative_party_popularity"}
    assert set(foreign_helpers(BETA)) == {"add_relative_party_popularity", "modify_radicalization_effect"}


def test_validation_flags_other_editions_raw_helpers_and_unknown_tags():
    from core.validation import validate_project
    project = make_sample_project()
    f = project.focuses[0]
    f.completionReward = CompletionReward(
        items=[RewardItem(kind="puppet", params={"target": "GRL"})],
        rawLines=["set_temp_variable = { rad_change = -5 }", "modify_radicalization_effect = yes",
                  "add_relative_party_popularity = yes"])
    project.countryTag = "MEX"
    known = {"MEX", "GRN", "USA"}
    with edition_context("beta"):
        issues = validate_project(project, known_country_tags=known)
    codes = [i.code for i in issues]
    assert codes.count("focus.reward.editionHelper") == 2
    helper_msgs = " ".join(i.message for i in issues if i.code == "focus.reward.editionHelper")
    assert "modify_radicalization_effect" in helper_msgs and "add_relative_party_popularity" in helper_msgs
    tag_issues = [i for i in issues if i.code == "focus.reward.tag.unknown"]
    assert len(tag_issues) == 1 and "GRL" in tag_issues[0].message and tag_issues[0].focusId == f.id
    assert all(i.severity == "warning" for i in issues if "edition" in i.code or "tag.unknown" in i.code)
    # Under main the raw radicalization line is fine and GRL exists there
    with edition_context("main"):
        issues = validate_project(project, known_country_tags={"MEX", "GRL"})
    assert not [i for i in issues if i.code in ("focus.reward.tag.unknown",)]
    assert [i.message for i in issues if i.code == "focus.reward.editionHelper"] == []
    # No tag list → tag check skipped entirely
    with edition_context("beta"):
        issues = validate_project(project)
    assert not [i for i in issues if "tag.unknown" in i.code]


def test_validation_flags_unknown_project_tag_and_condition_tag():
    from core.validation import validate_project
    from core.types import AvailabilityRule
    project = make_sample_project()
    project.countryTag = "NOR"                                   # renamed NRY in the beta
    project.focuses[0].available = AvailabilityRule(items=[RewardItem(kind="in_faction_with", params={"tag": "LOG"})])
    issues = validate_project(project, known_country_tags={"NRY", "MEX"})
    codes = {i.code for i in issues}
    assert "project.countryTag.unknown" in codes
    assert "focus.available.tag.unknown" in codes
