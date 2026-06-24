from __future__ import annotations

from core.country_tags import MD_COUNTRY_TAGS
from ui.country_tag_picker import clean_country_tag_text


def test_usa_country_tag_uses_full_display_name() -> None:
    usa = next(entry for entry in MD_COUNTRY_TAGS if entry.tag == "USA")

    assert usa.name == "United States of America"


def test_country_tag_picker_display_text_cleans_to_tag() -> None:
    assert clean_country_tag_text("USA - United States of America") == "USA"
    assert clean_country_tag_text("usa") == "USA"
