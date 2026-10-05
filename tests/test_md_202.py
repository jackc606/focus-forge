"""Millennium Dawn 2.0.2: the Communist-State → communist_state rename, the
doctrine discount categories, and research categories MD 2.0 dropped."""
from __future__ import annotations

from core.exporters import export_country_history, export_country_localisation
from core.ideologies import (
    IDEOLOGY_TREE,
    canonical_sub_ideology,
    has_legacy_ideology_token,
    rename_legacy_ideology_tokens,
)
from core.md_migrate import describe_counts, migrate_project
from core.md_parties import MD_PARTY_SUBIDEOLOGY_BY_INDEX
from core.presets import LEGACY_TECH_CATEGORY_HINTS, MD_TECH_CATEGORIES
from core.reward_presets import build_reward_item_lines, create_reward_item
from core.sample_project import make_sample_project
from core.serialization import project_from_dict, project_to_dict
from core.types import CompletionReward, CountryData, LeaderData, PartyData, RewardItem
from core.validation import validate_project


# ----- Communist-State → communist_state ------------------------------------------

def test_sub_ideology_is_the_202_id():
    assert "communist_state" in IDEOLOGY_TREE["communism"]
    assert "Communist-State" not in IDEOLOGY_TREE["communism"]
    assert MD_PARTY_SUBIDEOLOGY_BY_INDEX[4] == "communist_state"
    assert canonical_sub_ideology("Communist-State") == "communist_state"
    assert canonical_sub_ideology(" Conservative ") == "Conservative"


def test_rename_only_touches_md_derived_tokens():
    cases = {
        "ideology = Communist-State": "ideology = communist_state",
        "add_country_leader_trait = emerging_Communist-State": "add_country_leader_trait = emerging_communist_state",
        "Communist-State_leader": "communist_state_leader",
        "RUS.Communist-State_desc": "RUS.communist_state_desc",
        "MEX_Communist-State_flag": "MEX_Communist-State_flag",   # the project's own id
        "Communist-States": "Communist-States",
    }
    for old, new in cases.items():
        assert rename_legacy_ideology_tokens(old)[0] == new
    assert has_legacy_ideology_token("ideology = Communist-State")
    assert not has_legacy_ideology_token("MEX_Communist-State_flag")


def _project_with_old_ideology():
    p = make_sample_project()
    p.countryTag = "MEX"
    p.country = CountryData(
        parties=[PartyData(ideology="communism", name="PCM", subIdeology="Communist-State",
                           description="Old guard.")],
        leaders=[LeaderData(name="Ana", ideology="Communist-State",
                            traits=["emerging_Communist-State", "Communist-State_leader"])])
    return p


def test_old_projects_load_with_the_new_id():
    data = project_to_dict(_project_with_old_ideology())
    loaded = project_from_dict(data)
    leader = loaded.country.leaders[0]
    assert leader.ideology == "communist_state"
    assert leader.traits == ["emerging_communist_state", "communist_state_leader"]
    assert loaded.country.parties[0].subIdeology == "communist_state"


def test_export_writes_the_new_id_even_for_unmigrated_data():
    p = _project_with_old_ideology()
    history = export_country_history(p)
    assert "ideology = communist_state" in history
    assert "traits = { emerging_communist_state communist_state_leader }" in history
    assert "Communist-State" not in history
    loc = export_country_localisation(p)
    assert " MEX.communist_state:0" in loc and " MEX.communist_state_desc:0" in loc
    assert "Communist-State" not in loc


def test_migration_and_validation_cover_raw_script():
    p = make_sample_project()
    f = p.focuses[0]
    f.completionReward = CompletionReward(rawLines=[
        "create_country_leader = { name = \"X\" ideology = Communist-State traits = { emerging_Communist-State } }",
        "set_country_flag = MEX_Communist-State_flag"])
    codes = [i.code for i in validate_project(p) if i.focusId == f.id]
    assert "script.ideology.renamed" in codes
    counts = migrate_project(p, dry_run=True)
    assert counts["Communist-State"] == 2
    assert "Communist-State → communist_state (2×)" in describe_counts(counts)
    migrate_project(p)
    assert f.completionReward.rawLines == [
        "create_country_leader = { name = \"X\" ideology = communist_state traits = { emerging_communist_state } }",
        "set_country_flag = MEX_Communist-State_flag"]
    assert "script.ideology.renamed" not in [i.code for i in validate_project(p)]


# ----- doctrine discounts ---------------------------------------------------------

def test_doctrine_discount_uses_doctrine_folders():
    item = create_reward_item("doctrine_cost_reduction")
    assert item["params"]["category"] == "land_doctrine"
    item["params"]["category"] = "CAT_naval_doctrine"          # stored by an older version
    assert "	category = naval_doctrine" in build_reward_item_lines(item)


def test_migration_renames_doctrine_categories():
    p = make_sample_project()
    f = p.focuses[0]
    f.completionReward = CompletionReward(
        items=[RewardItem(kind="doctrine_cost_reduction",
                          params={"name": "x", "category": "CAT_air_doctrine", "uses": 1,
                                  "costReduction": 0.3})],
        rawLines=["add_doctrine_cost_reduction = { category = CAT_land_doctrine uses = 1 cost_reduction = 0.5 }"])
    counts = migrate_project(p)
    assert counts == {"CAT_air_doctrine": 1, "CAT_land_doctrine": 1}
    assert f.completionReward.items[0].params["category"] == "air_doctrine"
    assert "category = land_doctrine" in f.completionReward.rawLines[0]


# ----- research categories MD 2.0 dropped ------------------------------------------

LIVE = frozenset(MD_TECH_CATEGORIES) | {"CAT_armored_personnel_carriers"}


def _tech_issues(items=None, raw=None):
    p = make_sample_project()
    f = p.focuses[0]
    f.completionReward = CompletionReward(items=items, rawLines=raw)
    return [i for i in validate_project(p, tech_categories=LIVE)
            if i.code == "script.techCategory.unknown"]


def test_dead_research_categories_warn_with_a_data_backed_hint():
    issues = _tech_issues(
        items=[RewardItem(kind="tech_bonus", params={"name": "a", "bonus": 0.5, "uses": 1,
                                                     "category": "CAT_apc"}),
               RewardItem(kind="tech_bonus", params={"name": "b", "bonus": 0.5, "uses": 1,
                                                     "category": "CAT_industry"})],
        raw=["add_tech_bonus = { bonus = 0.5 uses = 1 category = CAT_inf_wep }",
             "add_doctrine_cost_reduction = { category = CAT_land_doctrine uses = 1 cost_reduction = 0.5 }"])
    msgs = sorted(i.message for i in issues)
    assert len(msgs) == 3 and all(i.severity == "warning" for i in issues)
    assert any("CAT_apc" in m and "CAT_armored_personnel_carriers" in m for m in msgs)
    assert any("CAT_inf_wep" in m and "pick a current category" in m for m in msgs)
    assert any("CAT_land_doctrine" in m and "Doctrine Cost Reduction (category land_doctrine)" in m for m in msgs)


def test_no_category_warnings_without_the_index():
    p = make_sample_project()
    p.focuses[0].completionReward = CompletionReward(rawLines=["add_tech_bonus = { category = CAT_inf_wep }"])
    assert not [i for i in validate_project(p) if i.code == "script.techCategory.unknown"]


def test_hint_targets_are_current_categories():
    # Every hint points at a category in MD 2.0's list, never at another dead one.
    assert not set(LEGACY_TECH_CATEGORY_HINTS) & set(LEGACY_TECH_CATEGORY_HINTS.values())
    assert all(v.startswith("CAT_") for v in LEGACY_TECH_CATEGORY_HINTS.values())
