"""The codebook in code: fixed lists, the `Extraction` schema, severity rules and the prompt.

`codebook.md` holds the same definitions in plain English. Keep the two in sync and bump
CODEBOOK_VERSION whenever either changes; bump PROMPT_VERSION whenever `prompt_text()`
output changes. Scripts import these lists; they never define their own copies.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CODEBOOK_VERSION = "0.2.1"
PROMPT_VERSION = "0.2.0"
TRIAGE_PROMPT_VERSION = "0.1.1"

MAX_ENTITIES = 5
MAX_QUOTE_WORDS = 25

# --- Fixed lists -------------------------------------------------------------------------

ALERT_CATEGORY_DEFINITIONS: dict[str, str] = {
    "resignation_call": "A public call for an official to resign, or a demand that they be dismissed.",
    "post_change": "A resignation, dismissal, suspension or appointment to a public post or state-company post that has actually happened.",
    "legal_action": "An arrest, indictment, investigation, criminal complaint filed, or case opened by a prosecutor or police.",
    "transition_milestone": "A formal step in the transfer of power: final results, constitution of parliament, nomination of a PM, government vote, handover, calling of the presidential election.",
    "new_actor": "A person or group newly entering political prominence: named for a post, launching a party, emerging as a spokesperson or candidate.",
    "legal_challenge": "Election complaints and appeals, court rulings, Constitutional Court cases, decrees and their legality, and private lawsuits by or against public figures over their public role.",
    "institution_change": "A change in control, leadership, mandate or conduct of a state company, regulator, public broadcaster or other institution (not just one appointment), or a closure, ownership or management decision that affects a major national media outlet's independence.",
    "protest_incident": "Protests, blockades, clashes, forced entries, attacks or security incidents with a political dimension.",
    "foreign_statement": "A statement, visit, sanction or measure by a foreign government, the EU or an international body about Serbia's transition.",
    "business_decision": "Contracts, tenders, concessions, privatisations, major state projects (EXPO 2027, Jadar, highways) and calls to review them.",
    "economic_stability": "Sanctions and licences affecting strategic companies (e.g. NIS), central-bank measures, bank liquidity or capital-flight claims, currency demand, and rating-agency or IFI assessments of the transition.",
}
ALERT_CATEGORIES: list[str] = list(ALERT_CATEGORY_DEFINITIONS)

CATEGORY_DEFINITIONS: dict[str, str] = {
    **ALERT_CATEGORY_DEFINITIONS,
    "background": "Relevant context that fits no alert category, e.g. commentary, explainers, campaign-finance reports, statistics with a political angle.",
}
CATEGORIES: list[str] = list(CATEGORY_DEFINITIONS)

ARTICLE_TYPE_DEFINITIONS: dict[str, str] = {
    "news": "Straight news report.",
    "analysis": "Explanatory or analytical piece by the outlet's journalists.",
    "opinion": "Column, op-ed or editorial; it speaks for the article.",
    "interview": "Question-and-answer or interview-based piece.",
    "official_release": "Press release or statement published by an institution or party.",
    "live_blog": "Running live coverage.",
    "other": "Anything else.",
}
ARTICLE_TYPES: list[str] = list(ARTICLE_TYPE_DEFINITIONS)

ACTION_DEFINITIONS: dict[str, str] = {
    "called_to_resign": "Someone publicly called on this person to resign.",
    "dismissal_demanded": "Someone publicly demanded that this person be dismissed or removed.",
    "resigned": "This person resigned.",
    "dismissed": "This person was dismissed or removed.",
    "suspended": "This person was suspended.",
    "appointed": "This person was appointed, elected or nominated to a post.",
    "investigated": "A prosecutor, police or audit body opened an investigation or case concerning this person or body.",
    "charged": "This person or body was indicted or charged.",
    "arrested": "This person was arrested or detained.",
    "accused": "A named party publicly accused this person or body of wrongdoing, without an official proceeding reported.",
    "sued": "A private lawsuit (civil, defamation or private criminal action) was brought against this person or body by a named party.",
    "statement": "This person or body made a statement that matters for the transition.",
    "other": "A relevant action that fits none of the above.",
}
ACTIONS: list[str] = list(ACTION_DEFINITIONS)

STAGE_DEFINITIONS: dict[str, str] = {
    "completed": "The article reports the action as having happened (filed, signed, carried out, taken effect).",
    "announced": "The action is announced, threatened, intended or planned, and the article does not report it as done.",
    "not_addressed": "The article does not make clear whether the action has happened.",
}
STAGES: list[str] = list(STAGE_DEFINITIONS)

STANCE_DEFINITIONS: dict[int, str] = {
    -2: "Clearly hostile: negative labels, unbalanced accusations, ridicule.",
    -1: "Somewhat negative: criticism dominates but other views appear.",
    0: "Neutral or balanced, or the article takes no position.",
    1: "Somewhat positive: favourable framing, praise outweighs criticism.",
    2: "Clearly favourable: positive labels, promotional framing.",
}

TOP_TIER_POSTS: list[str] = [
    "Prime Minister or any minister, including caretaker ministers",
    "President or acting President",
    "Speaker of the National Assembly",
    "Head of police or Minister of Interior",
    "Director of BIA (Security Information Agency)",
    "Supreme Public Prosecutor or the Prosecutor's Office for Organized Crime (TOK)",
    "RIK (Republic Electoral Commission) and its president",
    "REM (Regulatory Authority for Electronic Media)",
    "RTS director general or news chief",
    "Governor of the National Bank of Serbia",
    "CEO of a state company (e.g. Telekom Srbija, EPS, NIS, Srbijagas)",
]

NOT_ADDRESSED = "not_addressed"

AlertCategory = Literal[tuple(ALERT_CATEGORIES)]  # type: ignore[valid-type]
Category = Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]
ArticleType = Literal[tuple(ARTICLE_TYPES)]  # type: ignore[valid-type]
Action = Literal[tuple(ACTIONS)]  # type: ignore[valid-type]
Stage = Literal[tuple(STAGES)]  # type: ignore[valid-type]
Stance = Literal[tuple(STANCE_DEFINITIONS)]  # type: ignore[valid-type]


# --- Schema --------------------------------------------------------------------------------
# Every field is required (nullable where optional) so the schema works with strict
# structured outputs. Length limits are enforced by validators, not schema keywords.


class EntityRow(BaseModel):
    """One person or body and what happened to them in the story."""

    model_config = ConfigDict(extra="forbid")

    person_or_body: str = Field(description="actor_id from the actor list, or the name as written if not on the list.")
    proposed: bool = Field(description="True if person_or_body is not on the actor list.")
    role: str = Field(description="Their post or role as stated in the article, in English.")
    action: Action = Field(description="What happened to or was done by them.")
    stage: Stage = Field(description="Whether the action has happened (completed) or is only announced, threatened or intended (announced).")
    by_whom: str = Field(description="Who called for, did or alleged it; 'not_addressed' if the article does not say.")
    response: str = Field(description="Their reply as reported, in English; 'not_addressed' if none is reported.")
    stance: Stance = Field(description="The article's stance towards this person or body, -2 to 2.")


class Extraction(BaseModel):
    """The model's coding of one story."""

    model_config = ConfigDict(extra="forbid")

    relevant: bool = Field(description="True if the story concerns state-level political change in Serbia after the 25 Oct 2026 election, or a state-level matter in an alert category (including the independence of major national media), even if the article does not mention the election or transition.")
    category: Category
    secondary_category: AlertCategory | None = Field(description="A second, different alert category if the story clearly carries two; otherwise null.")
    top_tier: bool = Field(description="True if a current top-tier post holder or body is a subject of the main development; not for mere mentions or former holders.")
    article_type: ArticleType
    actors: list[str] = Field(description="actor_ids from the actor list that the story is about.")
    entities: list[EntityRow] = Field(description="0 to 5 rows.")
    summary: str = Field(description="Two sentences in English.")
    why_it_matters: str = Field(description="One sentence in English for a non-Serbian reader.")
    evidence_quote: str = Field(description="Verbatim from the article in its original language, at most 25 words.")

    @field_validator("entities")
    @classmethod
    def _max_entities(cls, rows: list[EntityRow]) -> list[EntityRow]:
        if len(rows) > MAX_ENTITIES:
            raise ValueError(f"at most {MAX_ENTITIES} entity rows")
        return rows

    @field_validator("evidence_quote")
    @classmethod
    def _quote_length(cls, quote: str) -> str:
        if len(quote.split()) > MAX_QUOTE_WORDS:
            raise ValueError(f"evidence_quote must be at most {MAX_QUOTE_WORDS} words")
        return quote

    @model_validator(mode="after")
    def _consistent(self) -> Extraction:
        if self.secondary_category is not None and self.secondary_category == self.category:
            raise ValueError("secondary_category must differ from category")
        if not self.relevant and (self.category != "background" or self.secondary_category or self.entities):
            raise ValueError("an irrelevant story is coded background with no secondary category or entities")
        return self


def check_actor_ids(extraction: Extraction, known_ids: set[str]) -> list[str]:
    """Return problems where the model used an unknown actor_id or mislabelled `proposed`."""
    problems = [f"unknown actor_id in actors: {a}" for a in extraction.actors if a not in known_ids]
    for row in extraction.entities:
        on_list = row.person_or_body in known_ids
        if on_list and row.proposed:
            problems.append(f"{row.person_or_body} is on the list but marked proposed")
        if not on_list and not row.proposed:
            problems.append(f"{row.person_or_body} is not on the list but not marked proposed")
    return problems


# --- Headline triage (before text extraction) ---------------------------------------------


class TriageItem(BaseModel):
    """The triage verdict for one headline."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The id given with the headline.")
    possibly_relevant: bool


class TriageBatch(BaseModel):
    """Verdicts for one batch of headlines, one per id."""

    model_config = ConfigDict(extra="forbid")

    items: list[TriageItem]


def triage_prompt_text() -> str:
    """Return the instructions for the headline triage pass."""
    return f"""You screen news headlines for a monitor of state-level political change in Serbia after the 25 October 2026 parliamentary election. Each line gives an id and a headline (Serbian or English).

Mark possibly_relevant true if the story could concern any of: posts and appointments, resignations or dismissals, calls to resign; prosecutions, arrests, investigations; the election results, rerun and transition; new political actors; court rulings and election complaints; state companies, regulators, the public broadcaster; closures, ownership or management decisions at major national media, pressure on or lawsuits involving journalists; protests and political incidents; foreign governments' or international bodies' statements on Serbia; state contracts and major projects; economic stability linked to the transition (sanctions, central bank, banks, currency).

Mark false only for stories clearly outside this: sport, entertainment, celebrities, weather, accidents and crime with no political angle, consumer and lifestyle news, foreign news not about Serbia.

When in doubt, mark true. Return exactly one item per id."""


# --- Severity (computed by script, never by the model) -----------------------------------


# Outlet groups that never confirm a story: uncredited aggregator copies, and party, union
# and association sources, which speak for themselves rather than corroborate (decided 3 Nov).
NON_CORROBORATING_GROUPS: frozenset[str] = frozenset({"aggregator", "primary_nonstate"})


@dataclass(frozen=True)
class ArticleRef:
    """One copy of a story: its id and the outlet group it is credited to."""

    article_id: str
    outlet_group: str


def compute_severity(articles: list[ArticleRef], top_tier: bool) -> tuple[int, list[str]]:
    """Return (severity, confirming article ids) for a story group.

    1 = one outlet group only; 2 = two or more outlet groups, or an official outlet;
    3 = meets 2 and the story is top-tier. Aggregator copies whose original outlet is
    unknown keep the `aggregator` group and do not count towards confirmation; nor do
    `primary_nonstate` sources (party, union and association sites).
    """
    official = next((a for a in articles if a.outlet_group == "official"), None)
    if official is not None:
        confirming = [official.article_id]
    else:
        first_by_group: dict[str, str] = {}
        for a in articles:
            if a.outlet_group not in NON_CORROBORATING_GROUPS:
                first_by_group.setdefault(a.outlet_group, a.article_id)
        confirming = list(first_by_group.values())[:2] if len(first_by_group) >= 2 else []
    if not confirming:
        return 1, []
    return (3 if top_tier else 2), confirming


# --- Actors and prompt ---------------------------------------------------------------------


def load_actors(path: Path | str) -> list[dict[str, str]]:
    """Read actors.csv, leaving out names that are only proposed."""
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return [row for row in csv.DictReader(fh) if row["status"] != "proposed"]


def _bullets(defs: dict) -> str:
    return "\n".join(f"- {key}: {text}" for key, text in defs.items())


def prompt_text(actors: list[dict[str, str]]) -> str:
    """Return the system prompt for coding one story against the codebook."""
    actor_lines = "\n".join(
        f"- {a['actor_id']}: {a['name']}" + (f" ({a['role']})" if a.get("role") else "")
        for a in actors
    )
    top_tier = "\n".join(f"- {p}" for p in TOP_TIER_POSTS)
    return f"""You code news stories for a monitor of state-level political change in Serbia after the 25 October 2026 parliamentary election. Readers are business people and foreign officials who do not read Serbian.

Rules:
- Code what the article says, not what you know. If the article does not say it, leave the field empty or use "{NOT_ADDRESSED}".
- Use only the categories, article types, actions and actor ids listed below. Never invent new ones.
- Always answer in English, except evidence_quote, which is copied verbatim from the article in its original language (at most {MAX_QUOTE_WORDS} words).
- Accusations are recorded with who made them (by_whom) and the accused party's reply (response).

relevant: true if the story concerns state-level political change in Serbia since the election (posts, institutions, prosecutions, the transition, protests, foreign reactions, state business decisions, economic stability, the independence of major national media and their journalists), or any state-level matter that fits an alert category. The article does not have to mention the election or the transition: a national state body, state company, senior official, national prosecution or strategic company such as NIS is enough, as is a closure, ownership or management decision at a major national media outlet, or a lawsuit between journalists and senior politicians, when that is the main development (not an interview or celebrity piece that only mentions layoffs or a change). A headline-only story is judged on what the headline says; missing detail is not a reason for false. False for local matters with no national angle (a school, a municipal utility), foreign events with no Serbian state angle, and routine government business. If false: category "background", no secondary_category, no entities.
category: use "background" only if no alert category fits. transition_milestone is for news that a formal step has just happened or been officially scheduled (results published by RIK, a rerun ordered, parliament constituted). Commentary, analysis or retrospectives that discuss the election outcome without reporting a new formal step are background.

category (choose one):
{_bullets(CATEGORY_DEFINITIONS)}

secondary_category: a second, different alert category only when the story clearly carries two; otherwise null.

top_tier: true only if a current holder of one of these posts, or one of these bodies, is a subject of the story's main development. False if the story merely mentions them, or concerns a former holder (for example Aleksandar Vučić, who is no longer president). Posts and bodies:
{top_tier}

article_type:
{_bullets(ARTICLE_TYPE_DEFINITIONS)}

actors: the actor_ids below that the story is about. Do not list anyone not on the list here.

entities: 0 to {MAX_ENTITIES} rows, one per person or body something happened to or was done by. Use the actor_id when the person or body is on the list and set proposed to false; otherwise write the name as given in the article and set proposed to true.
action:
{_bullets(ACTION_DEFINITIONS)}
stage (whether the action has happened): never mark as completed what the article reports only as announced, threatened, planned or intended (for example "will file a lawsuit", "announced the closure"). Calls, demands, accusations and statements are completed once made.
{_bullets(STAGE_DEFINITIONS)}
stance (the article's stance towards this person or body): labels count; quoted criticism counts when it is not balanced by a reply or other view; opinion pieces speak for the article.
{_bullets(STANCE_DEFINITIONS)}

summary: two sentences. why_it_matters: one sentence explaining the significance to an outsider.

Actor list (actor_id: name (role)):
{actor_lines}
"""
