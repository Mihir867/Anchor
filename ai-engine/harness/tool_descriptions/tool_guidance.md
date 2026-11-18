# How the pipeline checks your work

Your output is machine-checked after every stage. Knowing the checks saves repair rounds.

Fact selection
- `quote` must be an exact substring of one cited item after whitespace/quote normalisation.
  Copy a whole sentence from the item; do not start or end mid-word; "..." may join two
  in-order fragments of the SAME item, each at least 12 characters.
- Each `metrics` entry must contain a number that appears in the cited items; each
  `named_entities` entry must appear verbatim in them. When unsure, leave the list empty.
- Cite every item a fact relies on, and only those.

Post writing
- Every number in any field (LinkedIn, caption, poster headline/kicker/stat) must appear in the
  cited items. "$2M" and "2 million" are treated as the same number; years count as numbers.
- Banned phrases (global list plus the loaded skill's `banned_phrases`) fail the post.
- LinkedIn 400-3000 chars, first line <= 210 chars, <= 2 emojis. Caption 120-2200 chars.
  <= 6 hashtags. Poster headline <= 80, kicker <= 48, stat <= 14 chars. Name the brand.
- A second, independent model then checks each claim against the cited items and flags
  exaggeration ("leading", "first", "award-winning") the evidence does not state.

Repair rounds
- When given PROBLEMS, fix each one at its source (remove or re-attribute the claim) and keep
  the rest of the draft. Do not swap one unsupported claim for another.
