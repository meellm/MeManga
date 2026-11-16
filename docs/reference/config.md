# Settings reference

<script setup>
import { release } from '../.vitepress/release'
</script>

Every setting in `config.yaml`, the file where MeManga keeps your settings
and your library: its type, its default, what it does and how to change it.
[Where MeManga keeps its files](../guide/install#where-memanga-keeps-its-files)
says where the file is; `memanga config path` prints it.

::: info How to read this page
- This page describes the **development version**.
- Settings marked <Badge type="info" :text="`Not in ${release.tag}`" /> have no effect in {{ release.tag }}.
- `memanga config get`, `config set`, `config path` and `config edit` are
  not in {{ release.tag }} either; there, change settings in the desktop
  app or with `memanga config`.
- Types, choices, limits and defaults are taken from the program itself.
- A **default** is the value in a new config file. A setting that is missing
  from your file uses its default. A few keys are not in a new file at all;
  their entry says what MeManga does while they are missing.
- Keys marked as set by MeManga record something the program did. Leave
  them as they are.
:::

## Change a setting

- **In the desktop app:** open **Settings** in the sidebar. Some settings
  are changed on the page they belong to, such as the sort order of the
  library.
- **On the command line:** `memanga config set KEY VALUE` changes one
  setting and checks the value first; `memanga config get KEY` prints one.
  `memanga config` on its own asks about the most common settings. See the
  [command reference](./cli#memanga-config).
- **In the file:** `memanga config edit` opens `config.yaml` in your editor
  and checks it when you close the editor. If you edit the file another
  way, close the desktop app first: it can save its own settings over your
  changes.

::: details Example config.yaml with every default
Every setting at its default, with a short description. A new config file
has the same values; you do not need to copy this file.

<<< ../../examples/config.example.yaml
:::

<!--@include: ./config-keys.md-->
