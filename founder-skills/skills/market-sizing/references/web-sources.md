# Opening the sources a sized figure rests on

Step 4's search results show a snippet of each page. A figure the sizing uses should be read from the page itself,
and the passage that states it recorded beside it. This file says how. It never stops a run: every failure below
means "leave the quote out and carry on".

## When

After the searches for Step 4, and again whenever a later step records a new research figure (a comparison redo,
a revision round). Do it in the main thread, which has the host's fetch tool; the sub-agents have none.

## How

1. For each research figure the sizing will use that you mark `sourced`, open its `source_url` with the host's
   fetch tool (`WebFetch`, or the host's equivalent). At most 8 pages per run: choose the figures the headline
   numbers rest on first.
2. Open only a URL that came from this run's own search results or from the founder's own documents, never one
   typed from memory. On Cowork a URL from a search result opens without an approval prompt; one seen nowhere
   earlier in the session asks first.
3. Find the sentence that states the figure and copy it into that entry's `quote` in `validation.json`, as the
   page says it (the number written the way the page writes it). One passage, at most 1,000 characters.
4. If there is no fetch tool, the fetch is refused or denied, the page fails to load, it is paywalled, or the
   figure is not on it: leave `quote` out and continue. Do not retry, do not ask the founder about it, and do not
   switch to a different page to find a match.

## What never to do

- Never write a `quote` from memory or from the search snippet alone.
- Never add a quote after the sizing has run. The report counts quotes from what the sizing recorded when it
  ran (`quote_checks` in `sizing.json`), so a later edit changes nothing, and a quote added to make the count
  look better is not a quote from a page.
- Never edit a figure's `value` to match a passage. If the page says something different, the research
  changed: record the page's figure and its source, and let the sizing run on it.

## What the report says

Sources Used (report.md) and Assumption Confidence (report.html) carry one sentence: of the sourced market
figures the sizing uses, how many have a recorded passage containing the figure. It is a disclosure, not a
defect: nothing to fix. It claims only what the record shows. A passage containing the figure is recorded; it
does not prove the page was opened, since a fetch tool returns a processed rendering of the page and a snippet
copied by hand would also pass. Exchange rates are not counted.
