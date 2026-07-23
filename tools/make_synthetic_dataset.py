#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор синтетического учебного набора данных «Обращения в службу поддержки».

Набор используется в сквозном учебном ИИ-проекте: обучающиеся оценивают
пригодность данных для постановки задачи, формулируют требования к системе ИИ
и рассчитывают экономику решения. Данные полностью синтетические: они не
содержат персональных данных и не связаны с реальными организациями, поэтому
их можно свободно публиковать и использовать в открытых репозиториях.

В данные намеренно заложены дефекты, которые обучающиеся должны обнаружить при
анализе пригодности:
  * дисбаланс классов (одна категория существенно преобладает);
  * пропуски в поле категории (часть обращений не размечена);
  * дубликаты текстов обращений;
  * выбросы во времени обработки;
  * сдвиг распределения во втором полугодии (появление новой категории).

Запуск:
    python tools/make_synthetic_dataset.py --rows 500 --seed 2026 \\
        --out resources/datasets/support-tickets-sample.csv

Скрипт не требует сторонних библиотек.
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

CATEGORIES = {
    "оплата": (0.34, ["не прошел платеж", "двойное списание", "не пришел чек",
                      "ошибка при оплате картой", "вернуть деньги за заказ"]),
    "доставка": (0.27, ["где мой заказ", "курьер не приехал", "изменить адрес доставки",
                        "посылка задерживается", "доставили не тот товар"]),
    "качество товара": (0.16, ["товар пришел поврежденным", "не соответствует описанию",
                               "брак упаковки", "не работает после включения"]),
    "личный кабинет": (0.13, ["не могу войти в аккаунт", "сбросить пароль",
                              "изменить номер телефона", "не приходит код подтверждения"]),
    "прочее": (0.10, ["как оформить возврат", "нужна справка для бухгалтерии",
                      "вопрос по бонусной программе"]),
}
NEW_CATEGORY = ("подписка", ["как отменить подписку", "списали за подписку без согласия",
                             "изменить тариф подписки"])
CHANNELS = ["чат", "почта", "телефон", "мобильное приложение"]


def weighted_choice(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for name, (weight, _) in CATEGORIES.items():
        cumulative += weight
        if roll <= cumulative:
            return name
    return "прочее"


def generate(rows: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    start = datetime(2025, 1, 1)
    records: list[dict] = []
    seen_texts: list[str] = []

    for i in range(1, rows + 1):
        created = start + timedelta(days=rng.randint(0, 364),
                                    hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
        second_half = created.month > 6

        # во втором полугодии появляется новая категория — сдвиг распределения
        if second_half and rng.random() < 0.12:
            category, texts = NEW_CATEGORY[0], NEW_CATEGORY[1]
        else:
            category = weighted_choice(rng)
            texts = CATEGORIES[category][1]

        text = rng.choice(texts)
        # дубликаты: примерно 4 % записей повторяют уже встречавшийся текст
        if seen_texts and rng.random() < 0.04:
            text = rng.choice(seen_texts)
        seen_texts.append(text)

        # время обработки: логнормальное распределение с выбросами
        minutes = round(rng.lognormvariate(2.6, 0.55), 1)
        if rng.random() < 0.02:
            minutes = round(minutes * rng.uniform(6, 12), 1)  # выброс

        # пропуски в разметке: около 7 % обращений не размечены
        label = "" if rng.random() < 0.07 else category

        records.append({
            "ticket_id": f"T-{i:05d}",
            "created_at": created.isoformat(sep=" ", timespec="minutes"),
            "channel": rng.choice(CHANNELS),
            "text": text,
            "category": label,
            "handling_minutes": minutes,
            "resolved": "да" if rng.random() < 0.93 else "нет",
        })
    return records


def write_csv(records: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(records)


def report(records: list[dict]) -> None:
    total = len(records)
    unlabeled = sum(1 for r in records if not r["category"])
    texts = [r["text"] for r in records]
    unique_texts = len(set(texts))
    counts: dict[str, int] = {}
    for r in records:
        key = r["category"] or "(не размечено)"
        counts[key] = counts.get(key, 0) + 1
    print(f"Сформировано записей: {total}")
    print(f"Не размечено: {unlabeled} ({unlabeled / total:.1%})")
    print(f"Уникальных формулировок обращений: {unique_texts} "
          f"(низкая вариативность текста — обучающиеся должны это заметить)")
    print("Распределение по категориям:")
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<18} {count:>5} ({count / total:.1%})")
    times = sorted(r["handling_minutes"] for r in records)
    print(f"Время обработки, мин.: медиана {times[total // 2]:.1f}, максимум {times[-1]:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Генератор учебного набора данных")
    parser.add_argument("--rows", type=int, default=500, help="число записей")
    parser.add_argument("--seed", type=int, default=2026, help="зерно генератора")
    parser.add_argument("--out", default="resources/datasets/support-tickets-sample.csv",
                        help="путь к файлу результата")
    args = parser.parse_args()

    records = generate(args.rows, args.seed)
    write_csv(records, Path(args.out))
    report(records)
    print(f"\nФайл записан: {args.out}")


if __name__ == "__main__":
    main()
