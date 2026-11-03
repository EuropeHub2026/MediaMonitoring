# Codebook

**Version 0.2.0** (3 Nov 2026). Prompt version 0.2.0. Triage prompt version 0.1.1.

This is the plain-English codebook for the Serbia Post-Election Monitor. `codebook.py`
holds the same lists, the `Extraction` schema and the prompt. Keep the two in sync and
bump the version in both whenever either changes. Before any change after v0.1.0, run
`10_validate.py` on the hand-coded sample and record the before and after numbers in the
change log at the end.

## Principles

- **Code what the article says, not what you know.** If the article does not say it, the
  field is empty or `not_addressed`.
- **Only the listed values.** Never invent categories, actions or actors.
- **English output**, except `evidence_quote`, which is verbatim in the original language,
  at most 25 words, and never published.
- **Accusations** are recorded with who made them and the accused party's reply.
- **Public figures and public roles only.**

## Unit of coding

A **story** is one event or announcement reported by one or more outlets. Copies of the
same story are grouped under one `story_id` at collection; the story is coded once, from
its fullest copy. A **thread** (`thread_id`) links stories about the same running issue on
different days (e.g. the NIS licence, a dismissal demand later met).

## Headline triage

Before any page is fetched, each story's headline is screened in batches by the cheaper
coding model. `possibly_relevant` is true if the story could fall under any category
above the line `background`, or concern economic stability linked to the transition. It
is false only for clearly unrelated stories (sport, entertainment, weather, non-political
crime, lifestyle, foreign news not about Serbia). **When in doubt, true:** triage is
tuned for recall, and the full coding decides `relevant`. Only possibly relevant stories
have their text extracted and coded.

## Story-level fields (coded by the model)

| Field | Values | Notes |
|---|---|---|
| `relevant` | yes / no | Yes if the story concerns state-level political change in Serbia since the 25 Oct 2026 election, or a state-level matter in an alert category. The article need not mention the election or transition. A closure, ownership or management decision at a major national media outlet, or a lawsuit between journalists and senior politicians, counts (media independence) when it is the main development; an interview or celebrity piece that only mentions layoffs or a change does not. Headline-only stories are judged on the headline; missing detail is not a reason for no. |
| `category` | one category below | `background` only if relevant and no alert category fits; `transition_milestone` is for news that a formal step just happened or was officially scheduled; commentary on the outcome with no new formal step is `background`. Irrelevant stories are `background`. |
| `secondary_category` | one alert category, or empty | Only when the story clearly carries two, and never the same as `category`. |
| `top_tier` | yes / no | Is a current holder of a top-tier post, or a top-tier body (list below), a subject of the main development? No for mere mentions and former holders. |
| `article_type` | see below | |
| `actors` | actor ids from `actors.csv` | Only listed actors. New names go in entity rows with `proposed: true`. |
| `summary` | two sentences | |
| `why_it_matters` | one sentence | Written for a reader who does not follow Serbian politics. |
| `evidence_quote` | ≤ 25 words, original language | The passage that supports the category. Never published. |

Not relevant (examples): household statistics, consumer trends, company news with no state
or transition angle, sport and culture unless tied to the transition, local matters with no
national angle (a school, a municipal utility), foreign events with no Serbian state angle,
routine government business.

## Article-level fields (from collection, not the model)

`outlet`, `outlet_group`, `reach_tier`, `language`, `text_status`. A story stores the set
of outlet groups and outlets across its copies. Aggregator copies are credited to the
original outlet's group when known.

## Categories

Alert categories, in no particular order:

- `resignation_call`: A public call for an official to resign, or a demand that they be
  dismissed. *Example: Student List candidates demand the dismissal of Telekom Srbija's
  CEO.*
- `post_change`: A resignation, dismissal, suspension or appointment to a public post or
  state-company post that has actually happened. *Example: the RTS director general
  resigns.*
- `legal_action`: An arrest, indictment, investigation, criminal complaint filed, or case
  opened by a prosecutor or police. *Example: TOK opens cases on complaints naming the
  foreign minister and ambassadors over diaspora voting.*
- `transition_milestone`: A formal step in the transfer of power: final results,
  constitution of parliament, nomination of a PM, government vote, handover, calling of
  the presidential election. *Example: RIK schedules the 1 November rerun at 53 polling
  stations.*
- `new_actor`: A person or group newly entering political prominence: named for a post,
  launching a party, emerging as a spokesperson or candidate. *Example: a Student List
  candidate sets out priorities as a would-be interior minister.*
- `legal_challenge`: Election complaints and appeals, court rulings, Constitutional Court
  cases, decrees and their legality, and private lawsuits by or against public figures
  over their public role. *Example: two RTS journalists announce lawsuits against
  Aleksandar Vučić (entity rows: `sued`, stage `announced`).*
- `institution_change`: A change in control, leadership, mandate or conduct of a state
  company, regulator, public broadcaster or other institution (not just one appointment),
  or a closure, ownership or management decision that affects a major national media
  outlet's independence. *Example: the Supreme Public Prosecutor orders a review of all 87
  prosecutor's offices. Example: management announces the closure of the Nova daily's
  print edition (stage `announced` until it happens).*
- `protest_incident`: Protests, blockades, clashes, forced entries, attacks or security
  incidents with a political dimension. *Example: citizens enter a pro-government TV
  station and interrupt its broadcast.*
- `foreign_statement`: A statement, visit, sanction or measure by a foreign government, the
  EU or an international body about Serbia's transition. *Example: the Kremlin and Kyiv
  react to the result.*
- `business_decision`: Contracts, tenders, concessions, privatisations, major state
  projects (EXPO 2027, Jadar, highways) and calls to review them. *Example: the Fiscal
  Council calls for a review of the largest state investment contracts.*
- `economic_stability`: Sanctions and licences affecting strategic companies (e.g. NIS),
  central-bank measures, bank liquidity or capital-flight claims, currency demand, and
  rating-agency or IFI assessments of the transition. *Example: the NBS extends a deadline
  for exchange offices amid higher euro demand.*

And:

- `background`: Relevant context that fits no alert category, e.g. commentary,
  explainers, campaign-finance reports, statistics with a political angle.

**Two categories.** A US congressman asking for sanctions on named Serbian businessmen is
`foreign_statement` with `secondary_category: business_decision`.

## Severity (computed by script, never by the model)

| Severity | Rule |
|---|---|
| 1 | Reported by one outlet group only. |
| 2 | Reported by two or more outlet groups, or by an `official` outlet. |
| 3 | Meets 2 and `top_tier` is yes. |

A story of severity 2 or 3 records the confirming article ids: two articles from different
outlet groups, or one official article. Aggregator copies whose original outlet is unknown
do not count towards confirmation, and neither do `primary_nonstate` sources (party, union
and association sites such as the Student List site or UNS): they speak for themselves
rather than corroborate. Formal appointments, decisions and legal actions are confirmed by
`official` sources (government, National Assembly, RIK, RTS, REM, prosecutors, courts).

## Top-tier posts and bodies

- Prime Minister or any minister, including caretaker ministers
- President or acting President
- Speaker of the National Assembly
- Head of police or Minister of Interior
- Director of BIA (Security Information Agency)
- Supreme Public Prosecutor or the Prosecutor's Office for Organized Crime (TOK)
- RIK (Republic Electoral Commission) and its president
- REM (Regulatory Authority for Electronic Media)
- RTS director general or news chief
- Governor of the National Bank of Serbia
- CEO of a state company (e.g. Telekom Srbija, EPS, NIS, Srbijagas)

## Article types

- `news`: Straight news report.
- `analysis`: Explanatory or analytical piece by the outlet's journalists.
- `opinion`: Column, op-ed or editorial; it speaks for the article.
- `interview`: Question-and-answer or interview-based piece.
- `official_release`: Press release or statement published by an institution or party.
- `live_blog`: Running live coverage.
- `other`: Anything else.

## Entity rows (0 to 5 per story)

One row per person or body something happened to or was done by. The trackers are built
from these rows only.

| Field | Notes |
|---|---|
| `person_or_body` | The actor id if on `actors.csv`; otherwise the name as written. |
| `proposed` | `true` when the name is not on `actors.csv`. Proposed names never appear in trackers or on the page until a reviewer adds them to `actors.csv`. |
| `role` | Their post or role as stated in the article. |
| `action` | One action below. |
| `stage` | `completed`, `announced` or `not_addressed` (below). |
| `by_whom` | Who called for, did or alleged it; `not_addressed` if not stated. |
| `response` | Their reply as reported; `not_addressed` if none. |
| `stance` | −2 to +2, the article's stance towards this person or body. |

### Actions

- `called_to_resign`: Someone publicly called on this person to resign.
- `dismissal_demanded`: Someone publicly demanded that this person be dismissed or removed.
- `resigned`: This person resigned.
- `dismissed`: This person was dismissed or removed.
- `suspended`: This person was suspended.
- `appointed`: This person was appointed, elected or nominated to a post.
- `investigated`: A prosecutor, police or audit body opened an investigation or case
  concerning this person or body.
- `charged`: This person or body was indicted or charged.
- `arrested`: This person was arrested or detained.
- `accused`: A named party publicly accused this person or body of wrongdoing, without an
  official proceeding reported. *Example: a Student List candidate alleges an attempted
  RSD 1 billion withdrawal from a state bank; the bank denies it (response).*
- `sued`: A private lawsuit (civil, defamation or private criminal action) was brought
  against this person or body by a named party.
- `statement`: This person or body made a statement that matters for the transition.
- `other`: A relevant action that fits none of the above.

### Stage

Whether the action has happened. Never mark as completed what the article reports only as
announced, threatened, planned or intended ("will file a lawsuit", "announced the
closure"). Calls, demands, accusations and statements are completed once made. When a
later story confirms the act, its own entity row is `completed`; the thread links the two.

- `completed`: The article reports the action as having happened (filed, signed, carried
  out, taken effect).
- `announced`: The action is announced, threatened, intended or planned, and the article
  does not report it as done.
- `not_addressed`: The article does not make clear whether the action has happened.

### Stance

- −2: Clearly hostile: negative labels, unbalanced accusations, ridicule.
- −1: Somewhat negative: criticism dominates but other views appear.
- 0: Neutral or balanced, or the article takes no position.
- +1: Somewhat positive: favourable framing, praise outweighs criticism.
- +2: Clearly favourable: positive labels, promotional framing.

Labels count. Quoted criticism counts when it is not balanced by a reply or another view.
Opinion pieces speak for the article.

## Actors

`actors.csv` lists parties and lists, institutions, state companies, foreign actors and
named officials. `status` is `seed` (initial list, awaiting reviewer sign-off),
`confirmed` (a reviewer has checked it) or `proposed` (suggested by the model, hidden until
confirmed). The prompt offers `seed` and `confirmed` actors only. A row is never deleted
when someone leaves a post: update `role` and `as_of`.

## Change log

| Version | Date | Change | Validation |
|---|---|---|---|
| 0.1.0 | 30 Oct 2026 | First version. | No hand-coded sample yet. |
| 0.1.1 | 30 Oct 2026 | Added headline triage (schema and prompt); story-level definitions unchanged. | No hand-coded sample yet. |
| 0.1.2 | 2 Nov 2026 | Widened `relevant`: state-level alert-category matters count without an explicit election link; headline-only stories judged on the headline; `background` narrowed. Prompt 0.1.1. | No hand-coded sample yet, so no `10_validate.py` numbers. Informal check on the 15 of 30 stories rejected under 0.1.0: 9 now relevant. |
| 0.1.3 | 2 Nov 2026 | `transition_milestone` limited to news of a new formal step, commentary on the outcome is `background`; `top_tier` limited to current holders who are a subject of the main development. Prompt 0.1.2. | No `10_validate.py` yet. Provisional check against 30 Claude-coded stories (not reviewer codes), 12 English and 18 Serbian: category 63% to 80%, `top_tier` 77% to 90%, `relevant` 90% unchanged. The fixes were designed on this same sample. |
| 0.2.0 | 3 Nov 2026 | Media-independence strand: `relevant`, `institution_change` and triage cover closure, ownership or management decisions at major national media and lawsuits involving journalists; `legal_challenge` covers private lawsuits by or against public figures; new action `sued`; new entity field `stage` (`completed` / `announced` / `not_addressed`). `primary_nonstate` outlet group does not count towards severity. Prompt 0.2.0, triage prompt 0.1.1. | No `10_validate.py` yet. Same 30 Claude-coded stories (not reviewer codes). Before (0.1.3): relevant 90%, category 80%, `top_tier` 90%. After (0.2.0, rerun after narrowing the media rule; 29 scored, 1 failed the quote limit): relevant 90%, category 86%, `top_tier` 90%. A first 0.2.0 run, before the narrowing, scored category 70%; four stories unrelated to the change flipped between the two runs, so run-to-run variation exceeds the measured difference. The sample has no media-independence or lawsuit stories and no hand-coded `stage`, so the new fields are unvalidated; two synthetic inputs (Nova/Radar closure, Memedović/Kovačević lawsuits) were coded as intended. |
