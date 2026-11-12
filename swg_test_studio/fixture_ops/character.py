"""Op family `character`: the test character itself (script.fixture.agent_character).

Read-backs of pools, level, credits, faction, posture, profession and buffs; setters for
the same through the libraries the server itself uses (respec for level and profession,
factions for standing, money for credits, buff for buffs, healing/pclib for heal and revive).
Every op acts only on the one registered non-god bot; nothing here can grant god mode or an
admin level. Bounds below are the named caps of devtools/zones/fixtures/agent_character.java.
See docs/fixture-character.md.
"""
import re

FIXTURE = "agent_character"

# Accepted NGE profession roadmaps: exactly gm.getRoadmapList() of a Dec 2011 script tree.
PROFESSIONS = ("smuggler_1a", "bounty_hunter_1a", "officer_1a", "commando_1a", "force_sensitive_1a",
               "medic_1a", "spy_1a", "entertainer_1a", "trader_0a", "trader_0b", "trader_0c", "trader_0d")
ALIGNED = ("Imperial", "Rebel", "Neutral")
PVP_TYPES = ("neutral", "covert", "declared", "onleave")
POSTURES = ("upright", "crouched", "prone", "sitting", "knocked_down")

POOL_MAX = 500000          # health/action current and max
LEVEL_MAX = 90             # rows of datatables/player/player_level
CREDITS_MAX = 10000000     # cash or bank target / transfer amount
STANDING_MIN, STANDING_MAX = -5000, 50000   # factions.FACTION_RATING_MIN; the library clamps to the rank max
BUFF_SECONDS_MAX = 86400
GIVE_COUNT_MAX = 25

TYPES = {
    "char_pool": r"[0-9]{1,6}",
    "char_level": r"[0-9]{1,2}",
    "char_credits": r"[0-9]{1,8}",
    "char_profession": "|".join(PROFESSIONS),
    "char_aligned": "|".join(ALIGNED),
    "char_faction": r"[A-Za-z][A-Za-z0-9_]{0,47}",
    "char_standing": r"-?[0-9]{1,5}(\.[0-9]{1,2})?",
    "char_pvp": "|".join(PVP_TYPES),
    "char_posture": "|".join(POSTURES),
    "char_seconds": r"[0-9]{1,5}",
    "char_count": r"[0-9]{1,2}",
}

RANGES = {
    "char_pool": (1, POOL_MAX),
    "char_level": (1, LEVEL_MAX),
    "char_credits": (0, CREDITS_MAX),
    "char_standing": (STANDING_MIN, STANDING_MAX),
    "char_seconds": (1, BUFF_SECONDS_MAX),
    "char_count": (1, GIVE_COUNT_MAX),
}

OPS = {
    # read-backs
    "stats": ((), False),
    "buffs": (("name?",), False),
    "standing": (("char_faction",), False),
    # pools and condition
    "setHealth": (("char_pool",), True),
    "setAction": (("char_pool",), True),
    "setMaxHealth": (("char_pool",), True),
    "setMaxAction": (("char_pool",), True),
    "healFull": ((), True),
    "incapacitate": ((), True),
    "revive": ((), True),
    "setPosture": (("char_posture",), True),
    # level, profession, skills
    "setLevel": (("char_level",), True),
    "setProfession": (("char_profession", "char_level?"), True),
    "revokeSkills": (("regex",), True),
    "resetExpertise": ((), True),
    # credits
    "setBank": (("char_credits",), True),
    "setCash": (("char_credits",), True),
    "depositCash": (("char_credits",), True),
    "withdrawCash": (("char_credits",), True),
    # faction
    "setFaction": (("char_aligned",), True),
    "setStanding": (("char_faction", "char_standing"), True),
    "setPvpType": (("char_pvp",), True),
    # buffs
    "applyBuff": (("name", "char_seconds"), True),
    "removeBuff": (("name",), True),
    # equipment and inventory
    "equipItem": (("oid",), True),
    "unequipItem": (("oid",), True),
    "giveStaticCount": (("name", "char_count"), True),
}

# giveStaticCount creates objects: it needs an open scenario and tags what it creates.
SCENARIO_OPS = frozenset({"giveStaticCount"})

# Same skill-pattern limits as the core grantSkills (agent_fixture.java): no quantified group,
# at most two unbounded and three quantifiers in total.
_QUANTIFIED_GROUP = re.compile(r".*\)[*+?].*")


def check(op, args):
    """Static checks beyond the argument regexes; raises ValueError."""
    if op == "revokeSkills":
        pattern = args[0]
        if _QUANTIFIED_GROUP.fullmatch(pattern):
            raise ValueError("revokeSkills: a quantified group is not allowed")
        if sum(pattern.count(c) for c in "*+") > 2 or sum(pattern.count(c) for c in "*+?") > 3:
            raise ValueError("revokeSkills: at most two '*'/'+' and three quantifiers")
        try:
            re.compile(pattern)
        except re.error:
            raise ValueError("revokeSkills: invalid pattern") from None
    if op == "setStanding" and args[0] in ("Neutral",):
        raise ValueError("setStanding: the Neutral faction has no player standing")
