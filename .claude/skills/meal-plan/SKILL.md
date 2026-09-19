---
name: meal-plan
description: >-
  Plan the household's weeknight dinners for the coming week and generate a
  consolidated grocery list, published as a styled Artifact. Use this skill
  whenever the user invokes /meal-plan, asks "what's for dinner this week",
  asks for a meal plan or grocery/shopping list for the week, or when it
  fires automatically on the Friday meal-planning Routine. ALSO use when the
  user asks to swap out one night's dinner, regenerate the grocery list, or
  adjust the plan for a dietary request or upcoming event. Do NOT use for a
  single one-off recipe request, general nutrition or cooking advice, meal
  prep for lunches/breakfasts (this skill covers dinners only unless the
  user explicitly asks to expand scope), or restaurant recommendations.
---

# Meal Plan

Taryn's household needs a low-effort answer to "what's for dinner" each
week, not a recipe-browsing session. This skill exists so that every Friday
(and any time it's invoked mid-week) produces the same reliable output:
three easy, healthy-ish weeknight dinners — one of them hands-off in the
slow cooker, for the night nobody wants to stand at the stove — and one
shopping list that's actually usable at the store — merged, organized by
aisle, and free of things already in the pantry.

## Household (fixed context — don't re-ask)

2 adults, 2 adolescent boys, 1 toddler girl. Plan portions accordingly
(adolescent boys eat like adults or more; toddler needs a soft/mild version
of the same meal, not a separate dish). Unless the user says otherwise in
the conversation or a prior note, assume no standing allergies or diet
restriction — but always honor whatever the user states inline for that
run (e.g. "no red meat this week," "Jake's away Tuesday," "keep it dairy
light").

## Core rule

Every dinner must have: a protein, be fairly healthy (balanced, not fried
or ultra-processed as the main event), and be realistic for a weeknight —
roughly 30 minutes of active effort or less. If a plan doesn't clear that
bar, cut it before presenting it.

## Workflow

1. **Determine the run mode.**
   - **Automated (Friday Routine) run**: the prompt says so explicitly, or
     there's no live back-and-forth possible. Skip all questions — proceed
     straight to generating the plan using the fixed household context,
     general pantry-staple assumptions (salt, oil, common spices, rice/pasta
     on hand), and nothing else. Never let an automated run stall waiting
     on an answer nobody can give it.
   - **Interactive run**: the user is actively chatting. Ask **one**
     compact question covering both leftovers/pantry items already on hand
     and any requests for the week (dietary tweaks, a night to skip, an
     ingredient to use up) — don't split this into multiple questions, and
     don't ask again if they already answered it earlier in the
     conversation or gave the info unprompted.

2. **Pick three dinners, one of them a slow cooker recipe.** Rotate
   proteins across the week (don't repeat the same one twice) and vary
   cuisine/prep style so it doesn't feel repetitive week to week. Exactly
   one of the three should be built around the slow cooker — a
   dump-and-go recipe with under 15 minutes of hands-on time, meant for a
   day nobody has the bandwidth to stand at the stove. The other two
   follow the usual bar: sheet-pan, one-pot, or simple stovetop/oven meals,
   nothing with more than ~6 active steps. Note a toddler-friendly
   adjustment inline where a dish runs spicy, tough to chew, or otherwise
   isn't a straightforward serve (e.g. "set aside plain pasta + chicken for
   [toddler] before adding sauce").

3. **Build the grocery list.** Consolidate ingredients across all three
   dinners into one list — merge duplicates (e.g. two dinners calling for
   an onion becomes one line, "2 onions"), and drop anything the user said
   they already have. Group by store section: Produce, Meat & Seafood,
   Dairy & Eggs, Pantry/Dry Goods, Frozen, Other. Skip a section header if
   it would be empty.

4. **Publish as an Artifact.** Load the `artifact-design` skill before
   writing the page — this is a real deliverable the household will look at
   on a phone in the kitchen or at the store, not a throwaway. Use the
   output format below as the content structure; let artifact-design guide
   the visual execution (typography, spacing, light/dark support). Give it
   a title like "Week of [Month Day]" so repeat weeks are distinguishable
   in the artifact gallery.

5. **Hand off.** Reply with the artifact link and a one-line summary of the
   three dinners. On an automated run, this reply is the entire output —
   there's no user present to react to it, so don't end with a question.

## Output format

Structure the artifact content as:

- **Header**: "Week of [date range]"
- **Three dinner cards**, one per night, each showing: night label (or
  "Night 1" if not date-bound; mark the slow-cooker one clearly, e.g.
  "Monday · slow cooker"), dish name, the protein, a one-line description,
  and any toddler-adjustment note.
- **Grocery list**: grouped by store section as in step 3, each item as a
  checkable line (`- [ ] item — quantity`) so it works as a shopping
  checklist.

## Calibration

Three dinners, one of them slow-cooker, and dinner-only is the default
scope — don't expand to seven nights, lunches, or breakfasts unless the
user asks for that explicitly in the request. Conversely, don't shrink
below three, don't drop the slow-cooker night, and don't skip the grocery
list even if the user only asked "what's for dinner" — the list is the
point of the skill, not an optional extra.

## Example

Interactive input: "/meal-plan, oh and we've got a ton of ground turkey in
the freezer already, use that on one night"

→ Ask once: "Got it, one night built around the ground turkey you've got.
Anything else already in the fridge/pantry I should plan around, or any
nights to skip?" Then proceed with three dinners — one of them a slow
cooker recipe, one featuring the turkey (turkey omitted from the grocery
list) — consolidated list, published artifact, link + one-line summary in
reply.

Automated Friday firing (no user present): generate immediately using
household defaults, publish the artifact, and reply with the link and
summary — no question asked.
