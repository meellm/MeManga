# Command reference

<script setup>
import { release } from '../.vitepress/release'
</script>

Every `memanga` command, with its aliases, arguments and options. To learn
the commands in the order you would use them, start with
[Use the command line](../guide/cli). For exit codes, JSON output and
running without a terminal, see [Use MeManga in scripts](./scripting).

::: info How to read this page
- This reference is produced from the program's own command definitions in
  the **development version**. {{ release.tag }} has fewer commands and
  options: see
  [Differences in the latest release](../guide/cli#differences-in-the-latest-release).
  On any version, `memanga --help` and `memanga COMMAND --help` show what
  that version accepts.
- The descriptions are the program's own help texts. They say what a command
  accepts; this page makes no further promise about how a command behaves.
- Words in capitals, such as `TARGET`, stand for a value you supply. Choices
  in braces, such as `{on,off}`, mean one of the listed words. Square
  brackets mean the part can be left out.
- Every command also accepts `-h` or `--help`.
:::

<!--@include: ./cli-commands.md-->
