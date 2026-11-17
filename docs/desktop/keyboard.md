# Keyboard

<script setup>
import { release } from '../.vitepress/release'
</script>

The shortcuts of the desktop app and how keyboard focus moves between its
controls. The reader has keys of its own; they are listed under
[Keyboard](./reader#keyboard) on the Reader page.

::: info Which version
In {{ release.tag }}, **Ctrl+K** and the usual keys of buttons, text fields
and dialogs already work. The other shortcuts, the keys for Library cards,
rows and theme cards, the keyboard-only focus ring and the rules for where
focus goes are in the development version.
:::

## Shortcuts

On macOS, **Ctrl** in this table is the **Command** key (⌘).

| Keys | Where | What it does |
|---|---|---|
| Ctrl+K | Anywhere in the app | Opens **Search** with the cursor in the search field |
| Ctrl+, | The main window | Opens **Settings** |
| Ctrl+F | **Library** and **Sources** | Puts the cursor in the filter field, with its text selected |
| Ctrl+F | **Search** | Puts the cursor in the search field, with its text selected |
| Alt+Left on Windows and Linux (on Windows also Backspace), Cmd+[ on macOS | A series' page | Back to the **Library** |

The keys for going back are the system's own **Back** keys, as Qt defines
them for each platform. The **Ctrl+F** and **Back** shortcuts work only
while their page is showing.

## Moving around

| Keys | What they do |
|---|---|
| Tab, Shift+Tab | Move to the next or previous control. This includes the Library's cards and rows, the continue-reading cards and the theme cards in Settings. |
| Enter, Space | Activate the focused button, card or row: a card opens its series. |
| Menu key, Shift+F10 | Open the quick actions of the focused Library card or row |
| Arrow keys, Enter | Choose an item in a menu or a drop-down, such as the Auto / Manual mode of a series |
| Page Up, Page Down | Scroll the page |
| Esc | Close a dialog |

A ring marks the control with keyboard focus. Clicking with the mouse does
not leave one.

**Where focus goes:**

- When you open a page from a control on another page, such as a card,
  focus moves to the first control of the new page.
- Choosing a page in the sidebar keeps focus in the sidebar.
- After a card's quick action, focus returns to that card.

For a step-by-step pass with the keyboard and a screen reader, see the
[accessibility checklist](https://github.com/meellm/MeManga/blob/main/docs/ACCESSIBILITY.md).
