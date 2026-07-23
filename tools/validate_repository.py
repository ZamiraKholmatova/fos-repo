#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Валидатор репозитория ФОС.

Проверяет внутреннюю непротиворечивость фонда оценочных средств:
  1. структура репозитория соответствует ожидаемой;
  2. все относительные ссылки в Markdown-файлах ведут на существующие объекты;
  3. каждый индикатор, заявленный в модели измерения, покрыт хотя бы одним КИМ;
  4. суммы баллов в рубриках совпадают с максимумами, заявленными в КИМ;
  5. итоговая сумма баллов по всем КИМ равна 100;
  6. в публикуемых файлах не осталось незаполненных маркеров.

Запуск:
    python tools/validate_repository.py [--root .] [--strict]

Код возврата: 0 — проверки пройдены, 1 — обнаружены ошибки.
Скрипт не требует сторонних библиотек.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXPECTED_DIRS = [
    "docs", "M1-ai-project-initiation", "M2-planning-economics",
    "Project", "Exam", "methodical-guidelines", "resources", "team", "data", "tools",
]
EXPECTED_FILES = ["README.md", "LICENSE.md", "CONTRIBUTING.md", "docs/rpd.md"]
PLACEHOLDER = re.compile(r"\[ЗАПОЛНИТЬ[^\]]*\]")
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
INDICATOR = re.compile(r"LC-\d\.\d")
SKIP_PLACEHOLDER_FILES = {"team/README.md", "LICENSE.md", "docs/quality-checklist.md"}


class Report:
    """Накопитель результатов проверки."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.passed: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def ok(self, msg: str) -> None:
        self.passed.append(msg)

    def summary(self) -> int:
        for line in self.passed:
            print(f"  [OK]      {line}")
        for line in self.warnings:
            print(f"  [ВНИМАНИЕ] {line}")
        for line in self.errors:
            print(f"  [ОШИБКА]  {line}")
        print()
        print(f"Пройдено: {len(self.passed)} | предупреждений: {len(self.warnings)} "
              f"| ошибок: {len(self.errors)}")
        return 1 if self.errors else 0


def md_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if ".git" not in p.parts)


def check_structure(root: Path, rep: Report) -> None:
    missing = [d for d in EXPECTED_DIRS if not (root / d).is_dir()]
    missing += [f for f in EXPECTED_FILES if not (root / f).is_file()]
    if missing:
        rep.error(f"отсутствуют обязательные объекты: {', '.join(missing)}")
    else:
        rep.ok("структура репозитория соответствует ожидаемой")


def check_links(root: Path, rep: Report) -> None:
    broken = []
    total = 0
    for path in md_files(root):
        text = path.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            total += 1
            file_part = target.split("#")[0]
            if not file_part:
                continue
            resolved = (path.parent / file_part).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(root)} -> {target}")
    if broken:
        rep.error(f"битые относительные ссылки ({len(broken)}): " + "; ".join(broken[:5]))
    else:
        rep.ok(f"относительные ссылки корректны (проверено {total})")


def declared_indicators(root: Path) -> set[str]:
    readme = (root / "README.md").read_text(encoding="utf-8")
    section = readme.split("## 2. Модель измерения")[-1].split("## 3.")[0]
    return set(INDICATOR.findall(section))


def check_coverage(root: Path, rep: Report) -> None:
    declared = declared_indicators(root)
    if not declared:
        rep.error("в модели измерения не найдено ни одного индикатора")
        return
    kim_paths = sorted(root.glob("M*/kim-*.md")) + [root / "Project/README.md", root / "Exam/README.md"]
    covered: dict[str, list[str]] = {}
    for path in kim_paths:
        if not path.exists():
            continue
        for ind in set(INDICATOR.findall(path.read_text(encoding="utf-8"))):
            covered.setdefault(ind, []).append(path.parent.name)
    uncovered = sorted(declared - set(covered))
    if uncovered:
        rep.error(f"индикаторы не покрыты ни одним КИМ: {', '.join(uncovered)}")
    else:
        rep.ok(f"все индикаторы покрыты КИМ ({len(declared)} из {len(declared)})")
    extra = sorted(set(covered) - declared)
    if extra:
        rep.warn(f"в КИМ встречаются индикаторы вне модели измерения: {', '.join(extra)}")


def parse_max_score(text: str) -> int | None:
    match = re.search(r"\*\*Максимальный балл:\*\*\s*(\d+)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\*\*Максимум:\*\*\s*(\d+)", text)
    return int(match.group(1)) if match else None


def sum_rubric(text: str) -> int:
    """Суммирует значения колонки «Макс.» в таблицах рубрики."""
    total = 0
    index = None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            index = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Макс." in cells:
            index = cells.index("Макс.")
            continue
        if index is not None and len(cells) > index and re.fullmatch(r"\d+", cells[index]):
            total += int(cells[index])
    return total


def check_scores(root: Path, rep: Report) -> None:
    pairs = [
        ("M1-ai-project-initiation/kim-01-practical-work.md", "M1-ai-project-initiation/rubric-01.md"),
        ("M1-ai-project-initiation/kim-02-practical-work.md", "M1-ai-project-initiation/rubric-02.md"),
        ("M1-ai-project-initiation/kim-03-peer-review.md", "M1-ai-project-initiation/rubric-03.md"),
        ("M2-planning-economics/kim-01-practical-work.md", "M2-planning-economics/rubric-01.md"),
        ("M2-planning-economics/kim-02-practical-work.md", "M2-planning-economics/rubric-02.md"),
        ("M2-planning-economics/kim-03-practical-work.md", "M2-planning-economics/rubric-03.md"),
        ("M2-planning-economics/kim-04-test.md", "M2-planning-economics/rubric-04.md"),
        ("M2-planning-economics/kim-05-business-game.md", "M2-planning-economics/rubric-05.md"),
        ("Project/README.md", "Project/rubric-01.md"),
        ("Exam/README.md", "Exam/rubric-01.md"),
    ]
    mismatched = []
    grand_total = 0
    for kim_rel, rubric_rel in pairs:
        kim_path, rubric_path = root / kim_rel, root / rubric_rel
        if not kim_path.exists() or not rubric_path.exists():
            rep.warn(f"пропущена пара КИМ/рубрика: {kim_rel}")
            continue
        declared = parse_max_score(kim_path.read_text(encoding="utf-8"))
        actual = sum_rubric(rubric_path.read_text(encoding="utf-8"))
        if declared is None:
            rep.warn(f"не удалось определить максимальный балл: {kim_rel}")
            continue
        grand_total += declared
        if declared != actual:
            mismatched.append(f"{rubric_rel}: сумма {actual} != {declared}")
    if mismatched:
        rep.error("расхождение баллов рубрик и КИМ: " + "; ".join(mismatched))
    else:
        rep.ok("суммы баллов в рубриках совпадают с максимумами КИМ")
    if grand_total and grand_total != 100:
        rep.error(f"сумма баллов по всем КИМ равна {grand_total}, ожидается 100")
    elif grand_total:
        rep.ok("итоговая сумма баллов по всем КИМ равна 100")


def check_placeholders(root: Path, rep: Report, strict: bool) -> None:
    found = []
    for path in md_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        if rel in SKIP_PLACEHOLDER_FILES:
            continue
        if PLACEHOLDER.search(path.read_text(encoding="utf-8")):
            found.append(rel)
    if found:
        message = f"остались незаполненные маркеры: {', '.join(found)}"
        rep.error(message) if strict else rep.warn(message)
    else:
        rep.ok("незаполненных маркеров в публикуемых файлах нет")


def main() -> int:
    parser = argparse.ArgumentParser(description="Валидация репозитория ФОС")
    parser.add_argument("--root", default=".", help="корень репозитория")
    parser.add_argument("--strict", action="store_true",
                        help="считать незаполненные маркеры ошибкой")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    print(f"Проверка репозитория: {root}\n")

    rep = Report()
    check_structure(root, rep)
    check_links(root, rep)
    check_coverage(root, rep)
    check_scores(root, rep)
    check_placeholders(root, rep, args.strict)
    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
