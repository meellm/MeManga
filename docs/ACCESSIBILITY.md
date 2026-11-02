# Accessibility smoke checklist

A short manual pass for the desktop GUI with a real screen reader. It checks
that controls announce a useful name (and, where it helps, a description of
which item they act on or which state is current). Run it after changing GUI
controls.

Screen readers: Orca (Linux), NVDA or Narrator (Windows), VoiceOver (macOS).
Use the screen reader's object/review navigation to move through each page;
keyboard reachability and color contrast have their own checks and are not
part of this list.

Start with a library of at least two manga, one with new chapters, and one
downloaded chapter.

## Sidebar

- [ ] Each nav item is announced by its plain name ("Library", "Downloads",
      "Search", "Notifications", "Sources", "Settings"), without stray padding.
- [ ] Items with a count badge also announce what the number means
      (for example "2 manga in library", "3 unread notifications").
- [ ] The auto-check bar in the footer is announced as "Auto-check progress".

## Library

- [ ] The filter field is announced as "Filter library". The sort box says
      what it does ("Sort library" or, where the platform announces a drop-down
      by its current choice, as on Linux, the description "Sort order of the
      library").
- [ ] The view toggles are announced as "Grid view" and "List view"; the active
      one says "Current view", the other what it switches to.
- [ ] Each cover card (grid) and row (list) is announced by the manga title,
      followed by status, chapter progress, new-chapter count and
      "opens details".
- [ ] Continue-reading cards are announced by title with the last read chapter.

## Detail

- [ ] "Remove" says which manga it removes.
- [ ] Each chapter's "Read" / "Download" / "Retry" / "Send" says which chapter
      it acts on.

## Search and Sources

- [ ] The search field is announced as "Search manga"; each "+ Add" says which
      title and source it adds.
- [ ] The sources filter field is announced as "Filter sources".
- [ ] Each source checkbox is announced with its source domain and its checked
      state; the "⋯" button is announced as "More actions" with the domain.

## Downloads

- [ ] An active download row's cancel button is announced as "Cancel download"
      with the chapter, and its bar as "Download progress".

## Reader

- [ ] The layout buttons are announced as "Continuous scroll", "Single page"
      and "Two-page spread"; the active one says "current layout".
- [ ] The zoom buttons are announced as "Zoom out" and "Zoom in".
- [ ] The bottom bar is announced as "Reading progress" with its value.

## Settings

- [ ] Tabs are announced as "General", "Kindle / Email", "Advanced", "About".
- [ ] Theme cards are announced as "Dark theme" / "Light theme"; the active one
      says "Selected".
- [ ] Download directory, file naming template, concurrent downloads slider,
      Kindle/SMTP fields, app password, daily auto-check time, max pages
      allowed to fail and post-processing command each announce their label,
      not their placeholder or an empty name.
- [ ] The Output Format and MangaDex Image Quality drop-downs say what they
      set, not only their current choice ("pdf", "Original").
