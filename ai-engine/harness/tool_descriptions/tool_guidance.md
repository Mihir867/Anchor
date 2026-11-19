# How the pipeline checks your work

Your output is machine-checked after every stage. Knowing the checks saves repair rounds.

Fact selection
- `category` is the POST TYPE: one of the loaded skill's post types, spelled as listed there.
  A set of posts should use different post types; never pick two facts about the same topic.
- Types that announce something new (Release, Launch, Opening, Collection drop, News) need a
  DATED cited item from the last 18 months. Undated site copy is a Feature spotlight, How-to or
  Proof point, never a launch.
- An event, webinar, offer or deadline whose date has passed is rejected: we cannot invite
  followers to it. Use it only as a recap, and only if the evidence reports what happened.
- Facts listed under ALREADY POSTED were published in earlier runs: do not pick them again, nor
  another fact on the same topic.
- Homepage hero copy and taglines are what followers already know; prefer deeper pages (case
  studies, blog posts, changelogs, press, pricing details, reviews).
- `quote` must be an exact substring of one cited item after whitespace/quote normalisation.
  Copy a whole sentence from the item; do not start or end mid-word; "..." may join two
  in-order fragments of the SAME item, each at least 12 characters.
- Each `metrics` entry must contain a number that appears in the cited items; each
  `named_entities` entry must appear verbatim in them. When unsure, leave the list empty.
- Cite every item a fact relies on, and only those.

Post writing
- Written as the brand in the first person ("we", "our"), naming the brand at least once.
  Referring to the brand from outside ("Acme says", "Acme's site states") fails the post.
- Introduction patterns fail the post: "Meet <brand>", "Introducing <brand>", "Say hello to",
  "<brand> is a <platform/company/tool...>", "Who we are".
- Every number in any field (LinkedIn, caption, poster headline/kicker/stat, slides) must
  appear in the cited items. "$2M" and "2 million" are treated as the same number; years count.
- Banned phrases (global list plus the loaded skill's `banned_phrases`) fail the post.
- LinkedIn: 500-2000 characters; the first line is the hook, under 200 characters, and must
  work before "see more"; short paragraphs separated by blank lines; a specific close (no
  "Thoughts?"); 0-2 emojis; at most 3 hashtags at the end.
- Instagram caption: 150-1000 characters; a hook line that stops the thumb, 2-4 short lines
  with line breaks, one concrete detail, a closing line inviting action (save, visit, book,
  try, tag someone); 1-3 fitting emojis, never a string of them.
- Hashtags: 3-5, specific to the subject (no #success/#motivation filler); at most 6 in total.
- Poster headline <= 80 chars (one idea, read in two seconds), kicker <= 48 chars (a neutral
  label matching the post type; "New"/"Launch" only for a dated announcement), stat <= 14 chars
  (one number+unit copied from the evidence, or empty).
- Carousel slides explain the cover, one idea each, 2-3 bullets of <= 120 chars, each bullet a
  specific fact from the material.
- A second, independent model then checks each claim against the cited items and flags
  exaggeration ("leading", "first", "award-winning") the evidence does not state.

Repair rounds
- When given PROBLEMS, fix each one at its source (remove or re-attribute the claim, rewrite
  the hook) and keep the rest of the draft. Do not swap one unsupported claim for another.
