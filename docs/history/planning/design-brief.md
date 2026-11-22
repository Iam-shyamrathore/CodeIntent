# Code Intent: visual and interaction brief

User-selected direction: light silver and ink, with restrained cobalt. Working name remains Code Intent.

## Direction

- **Product:** helps engineers recover the recorded reasons behind code and inspect the supporting history.
- **Character:** exact, composed, inquisitive.
- **World:** a source-review desk: code margins, annotations, revision marks, and carefully connected evidence.
- **Moments:** a claim unfolding into its original evidence; an earlier decision visibly yielding to a supported later decision.
- **Signature:** one continuous evidence trail that starts at an answer's claim and follows its source relationships.

The user's request for minimalism takes precedence over decorative scene/hero defaults in design guidance. The richness is the real investigation itself. The landing and product share the same typography, spacing, source treatments and evidence interaction.

## First visual system

Provisional tokens, to be reviewed in rendered screen studies rather than treated as final by description alone:

| Role | Starting value |
| --- | --- |
| Canvas | Porcelain silver `#F7F8F8` |
| Primary surface | White `#FFFFFF` |
| Selected/raised surface | Soft silver `#EEF0F1` |
| Main text | Ink `#172027` |
| Secondary text | Steel ink `#56616B` |
| Accent | Cobalt `#2454D8` |

Borders derive from the ink at a low opacity. Semantic error/conflict colours are added only for real statuses and always accompanied by words. Validate actual text/background contrast, including selected states, before freezing tokens.

Typography candidate: IBM Plex Sans for the interface and display; IBM Plex Mono confined to source, hashes and real technical identifiers. Compare a second restrained sans treatment in the screen-study stage. Self-host properly licensed font files, preserve notices, and decide by rendered legibility and character. No typography choice is final solely because it appears in a design skill.

- Type scale: 12/14/16 for supporting content and body; 24/32 for context headings; 56–72 for the desktop landing statement, reduced appropriately on mobile.
- Weights mostly 400 and 500; 600 only where it improves hierarchy.
- Spacing: 4/8/12/16/24/32/48/64/96. Related items sit closer than separate groups.
- Controls: 36 px compact, at least 44 px effective touch targets. Corners mostly 6–10 px; large source surfaces 12–16 px only when a bounded surface helps.
- Chrome remains quiet; the active claim and selected evidence receive the accent. Source highlighting is legible and selective.
- Shadows only for actual layering such as the evidence drawer. Alignment and surface hierarchy carry ordinary structure.

## Landing page

### Opening composition

Quiet navigation: wordmark, Method, Source, and Open demo. The page makes its case through an actual investigation, without invented adoption numbers or endorsements.

Proposed lead: **Know why this code exists.**

Supporting copy: **Trace the decisions behind a repository through its code, commits, and discussions. See what changed, and what the evidence can actually support.**

The main action opens the prepared live investigation. The hero's other major element is the real evidence trail for a verified question. It uses product components and real source data; it is not a screenshot of a fake app window. The question, supported answer, and first citation are readable before animation or hydration finishes.

Use an offset composition: the opening statement anchors the upper left, while the investigation occupies the broader plane below and to the right. The evidence line visually relates the two. It must remain balanced at actual viewport sizes, not just a single screenshot.

### Page sequence

1. Promise and a working, sourced example.
2. One documented case that shows why history changes the answer.
3. A compact example of honest uncertainty, using the same components.
4. Method: source collection, evidence relationships, dated decisions, coverage. Explain user value rather than library names.
5. Entry into the full investigation and restrained footer with source/licence credits.

Avoid adding sections merely to make the page long. A pricing table, testimonials and partner wall require real product/business evidence before they earn a place.

## Investigation workspace

### Default: reading and asking

The default screen optimizes for understanding one question. A compact repository rail can collapse; the readable answer is dominant. The evidence inspector opens when a claim is selected. A full graph is a deliberate secondary view.

```text
┌ Code Intent     repository / revision                  Index details ┐
│ Repository rail │ Question and follow-ups                            │
│                 │                                                   │
│ Recent          │ Short supported answer                             │
│ investigations  │ Claim with source reference                        │
│                 │ Focused evidence trail                             │
│                 │                                                   │
│                 │ Ask about this repository                   Send   │
└─────────────────┴───────────────────────────────────────────────────┘
```

### When evidence is selected

```text
┌ Code Intent     repository / revision                               ┐
│ Compact rail │ Answer and active claim   │ Evidence inspector        │
│              │                          │ Exact source excerpt      │
│              │ Evidence trail           │ Date / author / role      │
│              │                          │ Related code or diff      │
│              │ Follow-up composer       │ Open original source      │
└──────────────┴──────────────────────────┴────────────────────────────┘
```

At laptop widths the rail collapses before the answer becomes cramped. At narrow widths the inspector becomes a full-width sheet/tab. Reading the entire app never requires horizontally scrolling the page; individual code panes may scroll deliberately.

### Signature interaction: follow the evidence

1. The developer selects a source reference on a particular claim.
2. That claim becomes active; the relevant path is highlighted and the source inspector opens.
3. The exact span is selected in context. Source type, identity, date, role, and scope are visible.
4. A code/diff link connects the discussion to the implemented change.
5. If supported, the timeline shows a later replacement. The earlier decision is clearly marked as historical and the replacement explains the changed scope.

Animate the transition once in roughly 180–320 ms. Focus follows an explicit keyboard action and returns correctly when the inspector closes. Reduced-motion mode shows the same state without the movement. There is no continuously moving background or decorative graph motion.

The relationship view uses actual retrieved edges and evidence identities. Limit the initial neighbourhood to roughly 8–20 meaningful nodes, with explicit expansion. Labels should explain the path; a list provides the same information without graph navigation.

## Evidence and wording

- Support labels are direct, inferred, conflicting or insufficient; temporal labels are separate.
- Dates and revision identifiers remain visible when showing historical source. Never silently describe a historical finding as current.
- Original-source links use immutable code permalinks where available and stable discussion/comment links, with the locally stored snapshot clearly identified.
- Participants are labelled author, reviewer or commenter as supported by the source. Do not advertise an automatic current-owner recommendation.
- A missing answer states which rationale is unknown and what related facts the index does support.
- A partial index explains which source classes or date/path ranges are absent. It never disguises partial ingestion with a confidence number.

## Indexing, failure, and empty states

Repository import has a calm working screen with the real stages: collecting code, collecting history, connecting evidence, checking the index. Counters come from backend events. Unknown durations remain unknown rather than becoming a fabricated percentage.

Failures identify the failed stage and available recovery: rate limit, inaccessible repository, unsupported file, provider timeout, or incomplete evidence. Existing ready indexes stay usable during a failed refresh. Cancelling a job and leaving a browser page have distinct behaviour.

An empty workbench offers a few genuine questions supported by the selected corpus. Follow-ups can be typed freely; the examples are navigation aids, not hardcoded answer routes.

## Design review process

Use [Unslop by Damir Sokolovsky](https://github.com/heydamir/unslop), CC BY 4.0, together with the local frontend-design and anti-slop guidance. Preserve attribution in copied/adapted skill material and project credits as appropriate.

Unslop is a review workflow, not an application dependency. Apply its ordered passes to the landing and app states: spacing, colour, icons, copy, typography, layout, details, visuals, motion. The user's minimal direction controls how much visual richness is appropriate.

The skill asks for direction review before UI editing. This planning package supplies a concrete direction; the next stage supplies reviewable screen studies. Routine engineering choices and research proceed without repeated approval requests. No application UI is being edited during this planning turn.

### Visual acceptance

- The page remains recognizably Code Intent when the wordmark is covered because the evidence interaction and source composition belong to this product.
- The main action and answer are immediately legible. Secondary controls do not compete with them.
- All controls work, selected states correspond to real state, and no content requires animation to become visible.
- No clipped headlines, overflowing composers, unreadable diff text, or obscured focus at 360, 768, 1280 and 1440 px.
- Keyboard-only use, zoom, long questions/paths, empty evidence, provider errors, and reduced motion are checked.
- Review both whole-screen composition and the exact edges of overlays/source highlights. Correct visual issues before recording the demo.
