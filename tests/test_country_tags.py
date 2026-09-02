from __future__ import annotations

from core.country_tags import MD_COUNTRY_TAGS
from ui.country_tag_picker import clean_country_tag_text


def test_usa_country_tag_uses_full_display_name() -> None:
    usa = next(entry for entry in MD_COUNTRY_TAGS if entry.tag == "USA")

    assert usa.name == "United States of America"


def test_country_tag_picker_display_text_cleans_to_tag() -> None:
    assert clean_country_tag_text("USA - United States of America") == "USA"
    assert clean_country_tag_text("usa") == "USA"


# ---------------------------------------------------------------------------
# Live tag list from game-data roots
# ---------------------------------------------------------------------------

import pytest

from core import bridge_dispatch
from core.base_tree import apply_base_tree_to_project
from core.country_tags import (
    CountryTagPreset,
    build_country_tags,
    clean_loc_name,
    clear_country_tag_cache,
    country_name,
    country_tags_for_roots,
)
from core.sample_project import make_sample_project


def _write(root, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tags(root, name: str, body: str) -> None:
    _write(root, f"common/country_tags/{name}", body)


def _loc(root, name: str, body: str) -> None:
    _write(root, f"localisation/english/{name}_l_english.yml", "l_english:\n" + body)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_country_tag_cache()
    yield
    clear_country_tag_cache()


def test_build_parses_tags_skips_comments_and_sorts(tmp_path) -> None:
    _tags(tmp_path, "00_countries.txt",
          '#Europe\nGER = "countries/Germany.txt"\n\n'
          'ABK = "countries/Abkhazia.txt"\t# trailing comment\n'
          '# USA = "countries/USA.txt"\n')
    result = build_country_tags([str(tmp_path)])
    assert [p.tag for p in result] == ["ABK", "GER"]
    # No localisation -> the tag itself is the name.
    assert result[0] == CountryTagPreset(tag="ABK", name="ABK")


def test_build_returns_empty_when_no_tag_files(tmp_path) -> None:
    assert build_country_tags([str(tmp_path)]) == []
    assert build_country_tags([]) == []


def test_dynamic_tags_marker_skipped_but_dynamic_tags_kept(tmp_path) -> None:
    _tags(tmp_path, "zz_dynamic_countries.txt",
          'dynamic_tags = yes # any tags after this are temporary\n'
          'D01 = "countries/D01.txt"\nD02 = "countries/D02.txt"\n')
    assert [p.tag for p in build_country_tags([str(tmp_path)])] == ["D01", "D02"]


def test_later_root_wins_name_for_same_tag(tmp_path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _tags(a, "a_countries.txt", 'AAA = "countries/A.txt"\n')
    _loc(a, "countries", ' AAA:0 "From A"\n')
    _tags(b, "b_countries.txt", 'AAA = "countries/A.txt"\nBBB = "countries/B.txt"\n')
    _loc(b, "countries", ' AAA:0 "From B"\n')
    result = {p.tag: p.name for p in build_country_tags([str(a), str(b)])}
    assert result == {"AAA": "From B", "BBB": "BBB"}


def test_same_named_file_in_later_root_shadows_earlier(tmp_path) -> None:
    """HOI4 layers by relative path: MD's 00_countries.txt replaces vanilla's
    outright (MD does not declare replace_path for country_tags), so vanilla-only
    tags must NOT leak through."""
    vanilla, mod = tmp_path / "game", tmp_path / "mod"
    _tags(vanilla, "00_countries.txt", 'OLD = "countries/Old.txt"\nGER = "countries/Germany.txt"\n')
    _tags(vanilla, "01_extra.txt", 'EXT = "countries/Extra.txt"\n')
    _tags(mod, "00_countries.txt", 'GER = "countries/Germany.txt"\nNEW = "countries/New.txt"\n')
    result = [p.tag for p in build_country_tags([str(vanilla), str(mod)])]
    assert result == ["EXT", "GER", "NEW"]


def test_replace_path_drops_earlier_roots_tags(tmp_path) -> None:
    vanilla, mod = tmp_path / "game", tmp_path / "mod"
    _tags(vanilla, "vanilla.txt", 'OLD = "countries/Old.txt"\n')
    _tags(mod, "mod.txt", 'NEW = "countries/New.txt"\n')
    _write(mod, "descriptor.mod", 'name="Mod"\nreplace_path="common/country_tags"\n')
    assert [p.tag for p in build_country_tags([str(vanilla), str(mod)])] == ["NEW"]


def test_loc_name_bare_key_then_ideology_fallback_and_markup_stripped(tmp_path) -> None:
    _tags(tmp_path, "00.txt", 'USA = "x"\nABK = "x"\nKOR = "x"\nZZZ = "x"\n')
    _loc(tmp_path, "countries",
         ' USA:0 "£GFX_flag §YUnited States§!"\n'
         ' USA_democratic:0 "Democratic USA"\n'   # bare key wins over ideology
         ' ABK_democratic:0 "Democratic Abkhazia"\n'
         ' ABK_neutrality:0 "Abkhazia"\n'          # neutrality preferred among ideologies
         ' KOR_communism:0 "North Korea"\n'
         ' ZZZ_DEF:0 "not a name key"\n')
    _write(tmp_path, "localisation/french/countries_l_french.yml",
           'l_french:\n USA:0 "Etats-Unis"\n')  # other languages ignored
    result = {p.tag: p.name for p in build_country_tags([str(tmp_path)])}
    assert result == {"USA": "United States", "ABK": "Abkhazia",
                      "KOR": "North Korea", "ZZZ": "ZZZ"}


def test_later_root_ideology_name_beats_earlier_root_bare_name(tmp_path) -> None:
    """Vanilla names MAN with a bare key; MD redefines MAN as Manipur but only
    via ideology keys. The latest root that knows the tag must win."""
    vanilla, mod = tmp_path / "game", tmp_path / "mod"
    _tags(vanilla, "00_countries.txt", 'MAN = "x"\n')
    _loc(vanilla, "countries", ' MAN:0 "China"\n')
    _tags(mod, "00_countries.txt", 'MAN = "x"\n')
    _loc(mod, "countries", ' MAN_neutrality:0 "Manipur"\n')
    assert country_name([str(vanilla), str(mod)], "MAN") == "Manipur"


def test_clean_loc_name() -> None:
    assert clean_loc_name("£GFX_icon  §YSpaced   Name§!") == "Spaced Name"
    assert clean_loc_name("Plain") == "Plain"


def test_country_tags_for_roots_falls_back_to_static_when_empty(tmp_path) -> None:
    assert country_tags_for_roots([str(tmp_path)]) is MD_COUNTRY_TAGS
    assert country_tags_for_roots([]) is MD_COUNTRY_TAGS
    assert country_tags_for_roots(None) is MD_COUNTRY_TAGS


def test_country_tags_for_roots_is_cached_until_cleared(tmp_path) -> None:
    _tags(tmp_path, "00.txt", 'AAA = "x"\n')
    first = country_tags_for_roots([str(tmp_path)])
    assert [p.tag for p in first] == ["AAA"]
    _tags(tmp_path, "00.txt", 'AAA = "x"\nBBB = "x"\n')
    assert country_tags_for_roots([str(tmp_path)]) is first  # stale by design
    clear_country_tag_cache()
    assert [p.tag for p in country_tags_for_roots([str(tmp_path)])] == ["AAA", "BBB"]


def test_country_name_unknown_tag_returns_tag(tmp_path) -> None:
    _tags(tmp_path, "00.txt", 'AAA = "x"\n')
    _loc(tmp_path, "countries", ' AAA:0 "Alpha"\n')
    assert country_name([str(tmp_path)], "AAA") == "Alpha"
    assert country_name([str(tmp_path)], "QQQ") == "QQQ"


def test_apply_base_tree_uses_live_name_when_roots_given(tmp_path) -> None:
    _tags(tmp_path, "00.txt", 'FRA = "x"\n')
    _loc(tmp_path, "countries", ' FRA_neutrality:0 "Sixth Republic"\n')
    project = make_sample_project()
    project.countryTag = "FRA"
    apply_base_tree_to_project(project, roots=[str(tmp_path)])
    assert project.projectName == "Sixth Republic Base Tree"
    # Default (no roots) keeps the static-list behaviour.
    project.countryTag = "FRA"
    apply_base_tree_to_project(project)
    assert project.projectName == "France Base Tree"


def test_bridge_reference_data_uses_roots_provider_when_set(tmp_path) -> None:
    _tags(tmp_path, "00.txt", 'GRN = "x"\n')
    _loc(tmp_path, "countries", ' GRN_neutrality:0 "Greenland"\n')
    bridge_dispatch.set_roots_provider(lambda: [str(tmp_path)])
    try:
        ref = bridge_dispatch._op_reference_data(None, {})
        assert ref["countryTags"] == [{"tag": "GRN", "name": "Greenland"}]
    finally:
        bridge_dispatch.set_roots_provider(None)
    ref = bridge_dispatch._op_reference_data(None, {})
    assert len(ref["countryTags"]) == len(MD_COUNTRY_TAGS)


def test_param_widget_country_items_follow_live_list(monkeypatch) -> None:
    from ui import param_widgets

    live = [CountryTagPreset(tag="GRN", name="Greenland")]
    monkeypatch.setattr(param_widgets, "current_country_tags", lambda: live)
    monkeypatch.setattr(param_widgets, "_country_items_cache", (None, []))
    items = param_widgets._country_items()
    assert items == [("GRN", "GRN — Greenland")]
    assert param_widgets._country_items() is items  # same source list -> cached
    live2 = [CountryTagPreset(tag="GRL", name="Greenland")]
    monkeypatch.setattr(param_widgets, "current_country_tags", lambda: live2)
    assert param_widgets._country_items() == [("GRL", "GRL — Greenland")]
