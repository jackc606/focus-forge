"""The Millennium Dawn focus-authoring guide served to AI agents — Qt-free.

One text, two consumers: the bridge's ``guide`` op (so an in-app agent calling
``dispatch`` directly sees it) and the MCP server's ``md_focus_guide`` tool /
``author_md_focuses`` prompt. The pieces that ``reference_data`` also exposes
(reward / AI-weight / cost / layout conventions) are module constants and the
guide is *built from them*, so the two can never disagree. Lists of presets and
filters are derived from the registries for the same reason.
"""
from __future__ import annotations

from .presets import MD_FOCUS_FILTERS
from .reward_presets import REWARD_PRESETS
from .validation import MIN_SAME_ROW_DX

# Groups whose presets wrap Millennium Dawn scripted effects (as opposed to
# vanilla HOI4 effects). Named here so the guide can list them by kind.
_MD_GROUP_PREFIX = "Millennium Dawn"


def md_specific_reward_kinds() -> list:
    """Kinds of the reward presets that emit MD scripted-effect helpers — the
    ones a model is most tempted to write as rawLines even though a preset
    exists."""
    return [p.kind for p in REWARD_PRESETS if p.group.startswith(_MD_GROUP_PREFIX)]


# ----- conventions shared with reference_data ----------------------------------

LAYOUT_CONVENTION = {
    "minSameRowDx": MIN_SAME_ROW_DX,
    "note": (f"Focuses sharing a y row need x-distance >= {MIN_SAME_ROW_DX}; "
             "dx=1 makes the focus boxes overlap in-game. Vertical steps of "
             "dy=1 are fine. The validator warns via focus.position.tooClose."),
}

REWARD_AUTHORING_NOTE = (
    "Use structured items for everything that has a preset: completionReward = "
    '{"items": [{"kind": "<preset kind>", "params": {...}}]} — kinds and their '
    "params come from list_reward_presets (compact=true); availability conditions "
    "likewise via list_condition_presets into available.items. This INCLUDES the "
    "MD-specific effects that DO have presets: " + ", ".join(md_specific_reward_kinds()) +
    ". Structured items are validated, editable as cards in the GUI, visible to "
    "Stats and the pp economy, and export through the exact same builders. Use "
    "rawLines only for shapes no preset expresses (nested if/limit blocks, "
    "state-scoped blocks) — raw script is invisible to charts until someone runs "
    "Structure Raw Rewards."
)

AI_WEIGHT_AUTHORING_NOTE = (
    "EVERY real MD focus carries ai_will_do. Set aiWillDo (base; 10 = HOI4 default, "
    "0 = AI never picks it) and aiModifiers: a list of "
    '{"factor": n | "add": n, "trigger": {"items": [condition preset items], '
    '"rawLines": [...]}}. Idioms: factor 0 on the non-historical side of a mutex '
    "fork (or gate on has_country_flag / has_government); factor 0 while at war for "
    "economy focuses; factor 5-10 on the historical opening moves with a date < "
    "trigger; factor 0 for war paths unless war_support is high. Triggers use the "
    "same condition presets as `available`."
)

COST_CONVENTION = {
    "default": 10, "leaf": 5, "trivial": 1,
    "note": "10 = standard spine/branch-head/capstone (~70 days); 5 = granular "
            "leaf/follow-up; 1-3 = trivial. Vary cost by a focus's role.",
}


# ----- the guide ------------------------------------------------------------------

PROCEDURE = """\
## Procedure (follow in order)
1. `hello` -> `guide` -> `describe_op` for any op you have not used yet.
2. Read only what you need: `list_focuses` with `prefix` / `ids` / `x_min..y_max`
   bounds / `fields` / `limit`, and `get_focus` for the focuses you will connect
   to. Do not call `get_project` on large trees. `reference_data` takes
   `sections` and `list_reward_presets` / `list_condition_presets` take
   `compact=true` (or `kind` for one preset) — use them to save tokens.
3. Plan placement before writing: pick free cells; same-row focuses need
   dx >= 2; children go at y+1 under their parent.
4. Build each feature as ONE `batch` (add focuses first, then links). Never add
   focuses one call at a time when building more than ~3.
5. Every write returns `issues`. Fix every error before moving on; explain any
   warnings you leave.
6. After the batch: `validate`, then `screenshot` the region, then tell the user
   what you built and where.
7. NEVER call `save`, `export`, `load_project`, or delete focuses you did not
   create in this session unless the user explicitly asks for that action.
"""


def _filter_paragraph() -> str:
    names = ", ".join(f[len("FOCUS_FILTER_"):] for f in MD_FOCUS_FILTERS)
    return (
        "## Search filters (almost always present)\n"
        "~80% of focuses carry 1–2 `FOCUS_FILTER_*` tags matching their theme (pass\n"
        "them via the focus `filters` list). The standard Millennium Dawn set, common\n"
        f"ones first: {names}.\n"
        "Country-specific `FOCUS_FILTER_<TAG>_*` filters exist too, but only if the mod\n"
        "already defines them — an undefined filter silently never shows its button.\n"
    )


def build_guide() -> str:
    """Assemble the guide from the shared constants (called once at import)."""
    return f"""\
# Authoring Millennium Dawn focuses via the Focus Forge bridge

{PROCEDURE}
Real MD trees follow tight conventions. Match them — generic defaults read as AI slop.

## Cost (never uniform)
{COST_CONVENTION["note"]}
- `10` is the MD default (~70 days) — use for spine / branch-head / capstone focuses.
- `5` for granular leaf or follow-up focuses.
- `1`–`3` for trivial, near-free picks.
Roughly: early backbone trends to 10, deep sub-branches to 5. Don't inflate capstones above 10.

## Layout
{LAYOUT_CONVENTION["note"]}

## Icons (distinct & thematic)
One specific icon PER focus — real trees are ~1:1 unique. Reuse ONLY inside a tight
thematic cluster (e.g. several nuclear focuses sharing a nuclear icon is fine). Prefer
specific, evocative names over generic ones. Check `reference_data.iconPresets` and
existing focus icons via `get_focus` before picking. VERIFY every icon name with
`search_icons` before assigning it — a guessed GFX_ name that doesn't resolve renders
as a blank in-game; `search_icons` only returns names from the real sprite index, and
the bridge rejects an unresolved icon when icon roots are configured.

{_filter_paragraph()}
## Structure (lean into choice)
- ~⅔ of focuses have an `available` gate; ~⅓ are part of a `mutually_exclusive` fork.
- Prerequisites are a list of blocks. A plain id is one required block; several
  blocks are AND-ed (`["a","b"]` = need both). A nested list is one OR block
  (`[["a","b"]]` = need either). Use OR to let mutually-exclusive paths reconverge
  (e.g. a peace-OR-war fork merging back); separate AND blocks of mutex focuses
  are unreachable.
- Pay off a `set_country_flag` with a downstream `available = {{ has_country_flag = X }}`.

## Rewards
{REWARD_AUTHORING_NOTE}
Add a `custom_tooltip` item (or a `custom_effect_tooltip = KEY` raw line) in front
of scripted / `hidden_effect` blocks so the player sees what happened.

## AI weighting (every real MD focus has it)
{AI_WEIGHT_AUTHORING_NOTE}
A tree without weights plays randomly.

## Namespaces & tone
Events: `<localisationPrefix>.<n>` (e.g. SYR.1). Ideas: `<TAG>_<slug>`.
Write terse, dry, flavorful prose — a sentence or two of description per focus.
"""


MD_FOCUS_GUIDE = build_guide()
