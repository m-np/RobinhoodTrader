"""
Brain loader — assembles the agent's system prompt from skill files.

Skills live in brain/skills/<name>.md. Each skill is a markdown document
describing a trading domain. Strategy skills (base, aggressive_growth,
thesis_journal, red_day_protocol, catalyst_calendar) are always loaded.
Asset-class skills are loaded when their config knob is enabled.

To add a new always-on skill:
  1. Drop a .md file into brain/skills/
  2. Add its stem to _ALWAYS_LOAD below.

To add a knob-gated skill:
  1. Drop a .md file into brain/skills/
  2. Add an entry to SKILL_GATES: filename_stem → knob_key
  3. Enable the knob via the dashboard settings.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent / "skills"

# Always loaded — core strategy skills.
_ALWAYS_LOAD = [
    "base",
    "aggressive_growth",
    "thesis_journal",
    "red_day_protocol",
    "catalyst_calendar",
]

# Loaded only when the named config knob is truthy.
SKILL_GATES: dict[str, str] = {
    "stocks": "asset_stocks",
    "options": "asset_options",
    "crypto": "asset_crypto",
    "futures": "asset_futures",
}


def load_skill(name: str) -> str:
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        logger.warning("Brain skill file not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8").strip()


def active_skill_names(knobs: dict) -> list[str]:
    """Return ordered list of skill names given current knob values."""
    names = list(_ALWAYS_LOAD)
    for skill, knob in SKILL_GATES.items():
        if knobs.get(knob, False):
            names.append(skill)
    return names


def _inject_journal_depth(content: str, knobs: dict) -> str:
    """Replace the journal-depth line in stocks.md with live knob values."""
    import re
    core = int(knobs.get("min_journal_core", 1))
    growth = int(knobs.get("min_journal_growth", 1))
    moonshot = int(knobs.get("min_journal_moonshot", 2))
    return re.sub(
        r"Minimum journal entries for tier: Core \d+, Growth \d+, Moon Shot \d+",
        f"Minimum journal entries for tier: Core {core}, Growth {growth}, Moon Shot {moonshot}",
        content,
    )


def build_system_prompt(knobs: dict) -> str:
    """Assemble full system prompt from strategy skills + active asset skills."""
    parts: list[str] = []
    for name in active_skill_names(knobs):
        content = load_skill(name)
        if name == "stocks":
            content = _inject_journal_depth(content, knobs)
        if content:
            parts.append(content)
        else:
            logger.debug("Skipping empty or missing skill: %s", name)

    prompt = "\n\n---\n\n".join(parts)
    logger.debug(
        "Brain assembled: skills=%s, chars=%d",
        active_skill_names(knobs), len(prompt),
    )
    return prompt
