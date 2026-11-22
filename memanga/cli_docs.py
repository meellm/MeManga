"""Generate the command reference of the documentation site.

Usage: python -m memanga.cli_docs [--check]

The reference is read from the real argument parser, so commands, aliases
and options can't drift from the interface. The output does not depend on
the terminal width, the environment or the Python version: usage lines are
built here instead of taken from argparse's own formatter.
"""

import argparse
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

REFERENCE_PATH = "docs/reference/cli-commands.md"

HEADER = (
    "<!-- Generated from the argument parser by `python -m memanga.cli_docs`."
    " Do not edit by hand. -->"
)

# An environment variable that changes which options the parser shows.
_PARSER_ENV = ("MEMANGA_CLI_ONLY",)


def reference_parser() -> argparse.ArgumentParser:
    """The `memanga` parser as a default desktop-capable install builds it."""
    from .cli import build_parser

    saved = {name: os.environ.pop(name) for name in _PARSER_ENV
             if name in os.environ}
    try:
        return build_parser()
    finally:
        os.environ.update(saved)


def _text(value: str) -> str:
    """Escape help text for Markdown that is also a Vue template."""
    return (value.replace("\\", "\\\\")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("{{", "&#123;&#123;")
            .replace("*", "\\*"))


def _code(value: str) -> str:
    """Inline code, with a double fence when the value has a backtick."""
    fence = "``" if "`" in value else "`"
    pad = " " if fence == "``" else ""
    return f"{fence}{pad}{value}{pad}{fence}"


def _is_hidden(action: argparse.Action) -> bool:
    return action.help is argparse.SUPPRESS


def _help(action: argparse.Action, prog: str) -> str:
    """The action's help with argparse's %-placeholders filled in."""
    if not action.help:
        return ""
    params = {key: value for key, value in vars(action).items()
              if value is not argparse.SUPPRESS}
    params["prog"] = prog
    if params.get("choices") is not None:
        params["choices"] = ", ".join(str(c) for c in params["choices"])
    return " ".join((action.help % params).split())


def _value_name(action: argparse.Action) -> str:
    """What stands for the value of an option or positional."""
    if action.metavar is not None:
        if isinstance(action.metavar, tuple):
            return " ".join(action.metavar)
        return action.metavar
    if action.choices is not None:
        return "{" + ",".join(str(c) for c in action.choices) + "}"
    if action.option_strings:
        return action.dest.upper()
    return action.dest


def _with_nargs(action: argparse.Action, name: str) -> str:
    nargs = action.nargs
    if nargs == argparse.OPTIONAL:
        return f"[{name}]"
    if nargs == argparse.ZERO_OR_MORE:
        return f"[{name} ...]"
    if nargs == argparse.ONE_OR_MORE:
        return f"{name} [{name} ...]"
    if isinstance(nargs, int) and nargs > 1:
        return " ".join([name] * nargs)
    return name


def _option_label(action: argparse.Action) -> str:
    flags = ", ".join(action.option_strings)
    if action.nargs == 0:
        return flags
    return f"{flags} {_with_nargs(action, _value_name(action))}"


def _subparsers(parser: argparse.ArgumentParser
                ) -> Optional[argparse._SubParsersAction]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _commands(subparsers: argparse._SubParsersAction
              ) -> Iterator[Tuple[str, List[str], argparse.ArgumentParser, str]]:
    """Yield (name, aliases, parser, summary) in registration order.

    Aliases map to the same parser object as the name they stand for, and
    the name is registered first.
    """
    summaries = {pseudo.dest: pseudo.help or ""
                 for pseudo in subparsers._choices_actions}
    seen: Dict[int, List[str]] = {}
    order: List[Tuple[str, argparse.ArgumentParser]] = []
    for name, sub in subparsers.choices.items():
        if id(sub) in seen:
            seen[id(sub)].append(name)
        else:
            seen[id(sub)] = []
            order.append((name, sub))
    for name, sub in order:
        # A command registered without help= is left out of `--help`; its
        # description still says what it is.
        summary = summaries.get(name) or _first_sentence(sub.description)
        yield name, seen[id(sub)], sub, summary


def _first_sentence(text: Optional[str]) -> str:
    if not text:
        return ""
    flat = " ".join(text.split())
    head, dot, _rest = flat.partition(". ")
    return head + "." if dot else flat


def _usage(path: str, parser: argparse.ArgumentParser) -> str:
    """A one-line synopsis that does not depend on the terminal width."""
    parts = [path]
    options = [a for a in parser._actions
               if a.option_strings and not _is_hidden(a)
               and not isinstance(a, argparse._HelpAction)]
    if options:
        parts.append("[options]")
    for action in parser._actions:
        if action.option_strings or _is_hidden(action):
            continue
        if isinstance(action, argparse._SubParsersAction):
            # The top-level metavar is the whole list of command names.
            name = action.metavar or "COMMAND"
            if name.startswith("{"):
                name = "COMMAND"
            parts.append(name if action.required else f"[{name}]")
            continue
        parts.append(_with_nargs(action, _value_name(action)))
    return " ".join(parts)


def _description(parser: argparse.ArgumentParser) -> List[str]:
    if not parser.description:
        return []
    if issubclass(parser.formatter_class, argparse.RawDescriptionHelpFormatter):
        # Laid out by hand in the source: keep it as written.
        body = parser.description.strip("\n")
        return ["```text", *body.splitlines(), "```", ""]
    return [_text(" ".join(parser.description.split())), ""]


def _exclusive(parser: argparse.ArgumentParser) -> List[str]:
    lines = []
    for group in parser._mutually_exclusive_groups:
        names = [_code(a.option_strings[-1] if a.option_strings
                       else _value_name(a))
                 for a in group._group_actions if not _is_hidden(a)]
        if len(names) > 1:
            lines.append("Only one of " + ", ".join(names[:-1])
                         + " and " + names[-1] + " can be given.")
    return lines


def _arguments(parser: argparse.ArgumentParser, prog: str) -> List[str]:
    positionals, options = [], []
    for action in parser._actions:
        if (_is_hidden(action)
                or isinstance(action, (argparse._HelpAction,
                                       argparse._SubParsersAction))):
            continue
        if action.option_strings:
            label = _option_label(action)
        else:
            label = _value_name(action)
        entry = f"- {_code(label)}"
        text = _help(action, prog)
        if text:
            entry += f": {_text(text)}"
        (options if action.option_strings else positionals).append(entry)

    lines: List[str] = []
    if positionals:
        lines += ["**Arguments**", "", *positionals, ""]
    if options:
        lines += ["**Options**", "", *options, ""]
    exclusive = _exclusive(parser)
    if exclusive:
        lines += [*exclusive, ""]
    return lines


def _command_section(path: str, aliases: List[str], summary: str,
                     parser: argparse.ArgumentParser, prog: str,
                     level: int) -> List[str]:
    lines = [f"{'#' * level} {path}", ""]
    raw = issubclass(parser.formatter_class,
                     argparse.RawDescriptionHelpFormatter)
    flat = " ".join((parser.description or "").split())
    # A plain description that opens with the summary would say it twice.
    if summary and (raw or not flat.startswith(summary.rstrip("."))):
        lines += [_text(summary.rstrip(".") + "."), ""]
    if aliases:
        parent = path.rsplit(" ", 1)[0]
        label = "Alias" if len(aliases) == 1 else "Aliases"
        lines += [f"{label}: "
                  + ", ".join(_code(f"{parent} {a}") for a in aliases) + ".",
                  ""]
    lines += ["```text", _usage(path, parser), "```", ""]
    lines += _description(parser)
    lines += _arguments(parser, prog)

    nested = _subparsers(parser)
    if nested is not None:
        for name, sub_aliases, sub, sub_summary in _commands(nested):
            lines += _command_section(f"{path} {name}", sub_aliases,
                                      sub_summary, sub, prog, level + 1)
    return lines


def render_reference() -> str:
    parser = reference_parser()
    prog = parser.prog
    lines = [HEADER, "", "## Global options", "",
             "These go before the command.", "",
             "```text", _usage(prog, parser), "```", ""]
    lines += _arguments(parser, prog)

    subparsers = _subparsers(parser)
    if subparsers is not None:
        lines += ["## Commands at a glance", ""]
        commands = list(_commands(subparsers))
        for name, aliases, _sub, summary in commands:
            entry = f"- [{_code(f'{prog} {name}')}](#{prog}-{name})"
            if summary:
                entry += f": {_text(summary)}"
            lines.append(entry)
        lines.append("")
        for name, aliases, sub, summary in commands:
            lines += _command_section(f"{prog} {name}", aliases, summary,
                                      sub, prog, level=2)
    return "\n".join(lines).rstrip("\n") + "\n"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def generated_files(root: Path) -> Dict[Path, str]:
    return {root / REFERENCE_PATH: render_reference()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Fail if the generated reference differs")
    args = parser.parse_args(argv)
    root = _repo_root()
    stale = []
    for path, expected in generated_files(root).items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            stale.append(path.relative_to(root))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
    if stale:
        if args.check:
            parser.exit(1, "Outdated command reference: "
                        + ", ".join(map(str, stale))
                        + "\nRun: python -m memanga.cli_docs\n")
        print("Updated command reference: " + ", ".join(map(str, stale)))


if __name__ == "__main__":
    main()
