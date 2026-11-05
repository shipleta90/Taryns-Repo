---
name: grocery
description: >-
  Add items to the Cardona family's shared Todoist "Groceries" list, cleaned up,
  sorted into store sections, and never duplicated. Use whenever the user says
  "add X to groceries", "we need butter", "put ranch on the list", pastes a
  list of items, asks what's on the grocery list, or when the meal-plan skill
  hands over a week's ingredients. Do NOT use for to-do tasks that aren't
  shopping (those go to Todoist's Family project), or for recipe advice.
---

# Grocery

The family's one grocery list lives in **Todoist → project "Groceries"**. The
kitchen hub, Taryn's and Phillip's phones, Siri ("add butter to Groceries in
Todoist") and the Friday meal-plan routine all use that same list. This skill
is how Claude adds to it without making a mess.

## Store sections (Todoist sections in the Groceries project)

Produce · Meat & Seafood · Dairy & Eggs · Bakery · Pantry · Frozen · Household · Other

Create a section only if it's missing and an item needs it.

## Todoist API

Base `https://api.todoist.com/api/v1`, header
`Authorization: Bearer ${TODOIST_API_TOKEN:-injected}`. In a cloud session the
network proxy injects the real token for api.todoist.com, so the placeholder is
fine; never print or ask for the token.

- Projects: `GET /projects` → `{"results":[{id,name}], "next_cursor"}`; find "Groceries" (case-insensitive).
- Sections: `GET /sections?project_id=ID`; create: `POST /sections` `{"name","project_id"}`.
- Current items: `GET /tasks?project_id=ID` (follow `next_cursor`).
- Add: `POST /tasks` `{"content","project_id","section_id"}`.

## Workflow

1. **Read the list first** (project, sections, current items).
2. **Clean each new item**: plain name, sentence case, quantity at the end only
   if it matters ("Ranch dressing", "Eggs — 2 dozen", "Onions — 2"). Fix
   obvious voice-dictation slips ("lettuce romaine" → "Romaine lettuce").
3. **De-duplicate** against what's already there, ignoring case and
   singular/plural ("butter" = "Butter", "onion" = "Onions"). If it's already
   on the list, don't add it again; if the new quantity is bigger, mention it
   instead of changing the existing task.
4. **Pick a section** from the list above and add the task there.
5. **Reply** in one short line: what was added (by section) and what was
   already on the list. If Todoist can't be reached, say so plainly and give
   the cleaned list so nothing is lost — never claim items were added.

## When called by meal-plan

Meal-plan passes the consolidated ingredient list. Skip pantry staples it
marks as assumed (salt, oil, common spices). Add the rest with steps 2–5.
