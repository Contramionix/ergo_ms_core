#!/usr/bin/env python3
"""Собирает .claude/rules/*.md из .cursor/rules/*.mdc.

Источник правды — .cursor/rules. Каждое правило превращается в .claude/rules/*.md,
текст не меняется. Правила модулей modules/<имя>/.cursor/rules/*.mdc ложатся в
.claude/rules/modules/<имя>/: Claude Code читает только корневой .claude/rules
(с подкаталогами), вложенный modules/<имя>/.claude/rules он не видит. Каталог
.claude/rules/modules/ не коммитится, его пересобирает хук SessionStart.
- с globs — копия с полем paths, грузится при работе с подходящими файлами;
- с alwaysApply: true — копия без paths, грузится в каждой сессии.
Правила без globs и без alwaysApply Cursor подключает по описанию. Их текст не
копируется: в .claude/rules/rules-index.md (и modules/rules-index.md для модулей)
лежит оглавление с описанием и путём, его Claude Code видит в каждой сессии.
*.local.mdc (личные файлы, не коммитятся) попадают в .claude/rules/local/rules-index.md,
этот каталог тоже не в git.
Импорты @...mdc из CLAUDE.md не используются: Claude Code не раскрывает .mdc.

Использование:
    python3 .claude/scripts/sync_claude_rules.py          # записать копии
    python3 .claude/scripts/sync_claude_rules.py --check  # код 1, если копии устарели
    python3 .claude/scripts/sync_claude_rules.py --quiet  # для хука: молчит, если всё сошлось
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / ".cursor" / "rules"
DST = ROOT / ".claude" / "rules"
MODULES = ROOT / "modules"
MODULES_DST = DST / "modules"
INDEX = DST / "rules-index.md"
MODULES_INDEX = MODULES_DST / "rules-index.md"
LOCAL_INDEX = DST / "local" / "rules-index.md"
MARK = "<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->"
LINK = re.compile(r"\]\(([^)\s#]+)(#[^)\s]*)?\)")


def split_frontmatter(text):
    """Разбирает frontmatter построчно: Cursor терпит незакавыченные двоеточия, YAML — нет."""
    if not text.startswith("---\n"):
        raise ValueError("нет frontmatter")
    end = text.index("\n---\n", 4)
    meta = {}
    key = None
    for line in text[4:end].split("\n"):
        if line.startswith("  - ") and key:
            meta.setdefault(key, []).append(line[4:].strip().strip('"').strip("'"))
        elif ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip()
            meta[key] = value.strip() or []
    if isinstance(meta.get("globs"), str):
        meta["globs"] = [g.strip() for g in meta["globs"].split(",") if g.strip()]
    meta["alwaysApply"] = meta.get("alwaysApply") == "true"
    return meta, text[end + 5:]


def relink(body, src, dst):
    """Относительная ссылка из правила ведёт туда же, куда вела из .mdc."""

    def fix(match):
        target, anchor = match.group(1), match.group(2) or ""
        if "://" in target or target.startswith(("mailto:", "/")):
            return match.group(0)
        resolved = os.path.normpath(os.path.join(src.parent, target))
        slash = "/" if target.endswith("/") else ""
        return f"]({Path(os.path.relpath(resolved, dst.parent)).as_posix()}{slash}{anchor})"

    return LINK.sub(fix, body)


def render(meta, body, src, dst):
    globs = meta.get("globs") or []
    lines = []
    if globs:
        lines = ["---", "paths:"] + [f"  - {json.dumps(g, ensure_ascii=False)}" for g in globs] + ["---"]
    lines += [MARK, ""]
    return "\n".join(lines) + "\n" + relink(body.lstrip("\n"), src, dst)


def sources():
    """Пары (.mdc, копия): сначала корень, затем каждый checkout-нутый модуль."""
    for src in sorted(SRC.glob("*.mdc")):
        yield src, DST / f"{src.stem}.md", None
    for src in sorted(MODULES.glob("*/.cursor/rules/*.mdc")):
        module = src.parents[2].name
        yield src, MODULES_DST / module / f"{src.stem}.md", module


INDEX_INTRO = (
    "Cursor подключает эти правила по описанию, Claude Code сам их не грузит. "
    "Если задача совпадает с описанием, открой файл через Read до первых действий."
)


def render_index(title, entries, dst):
    lines = [MARK, "", f"# {title}", "", INDEX_INTRO, ""]
    for src, description in sorted(entries, key=lambda item: str(item[0])):
        link = Path(os.path.relpath(src, dst.parent)).as_posix()
        lines.append(f"- [`{src.relative_to(ROOT).as_posix()}`]({link}) — {description or 'без описания'}")
    return "\n".join(lines) + "\n"


def plan():
    wanted = {}
    shared, module_only, local = [], [], []
    for src, dst, module in sources():
        meta, body = split_frontmatter(src.read_text(encoding="utf-8").replace("\r\n", "\n"))
        description = str(meta.get("description") or "").strip().strip('"').strip("'")
        if src.name.endswith(".local.mdc"):
            # Локальные правила с адресами хоста: в оглавление, которое не коммитится, текст не копируем.
            local.append((src, description))
            continue
        if module and meta["alwaysApply"]:
            # alwaysApply в модуле запрещён; если всё же стоит — держим правило в границах модуля.
            meta["alwaysApply"] = False
            meta["globs"] = meta.get("globs") or [f"modules/{module}/**"]
        if not meta["alwaysApply"] and not meta.get("globs"):
            (module_only if module else shared).append((src, description))
            continue
        wanted[dst] = render(meta, body, src, dst)
    if shared:
        wanted[INDEX] = render_index("Правила по запросу", shared, INDEX)
    if module_only:
        wanted[MODULES_INDEX] = render_index("Правила модулей по запросу", module_only, MODULES_INDEX)
    if local:
        wanted[LOCAL_INDEX] = render_index("Локальные правила этого сервера", local, LOCAL_INDEX)
    return wanted


def generated_files():
    if not DST.exists():
        return []
    return [p for p in DST.rglob("*.md") if MARK in p.read_text(encoding="utf-8")]


def drop_empty_dirs():
    if not MODULES_DST.exists():
        return
    for folder in sorted(MODULES_DST.rglob("*"), reverse=True):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    if not any(MODULES_DST.iterdir()):
        MODULES_DST.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="не писать, только проверить")
    parser.add_argument("--quiet", action="store_true", help="ничего не печатать, если менять нечего")
    args = parser.parse_args()

    wanted = plan()
    stale = [p for p, text in wanted.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    orphans = [p for p in generated_files() if p not in wanted]

    if args.check:
        if stale or orphans:
            for p in stale:
                print(f"устарел: {p.relative_to(ROOT)}")
            for p in orphans:
                print(f"лишний: {p.relative_to(ROOT)}")
            print("Запустите: python3 .claude/scripts/sync_claude_rules.py", file=sys.stderr)
            return 1
        print(f"Копии актуальны: {len(wanted)} файлов")
        return 0

    for p, text in wanted.items():
        if p in stale:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    for p in orphans:
        p.unlink()
    drop_empty_dirs()
    if args.quiet and not stale and not orphans:
        return 0
    print(f"Записано: {len(stale)}, удалено лишних: {len(orphans)}, всего правил: {len(wanted)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
