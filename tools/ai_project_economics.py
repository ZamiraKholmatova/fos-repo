#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Калькулятор технико-экономических показателей ИИ-проекта.

Используется в КИМ-2.2 («Ресурсы, бюджет и риски ИИ-проекта») и КИМ-2.4
(контрольная работа) как эталон для проверки расчетов обучающихся,
а также как инструмент подготовки вариантов заданий.

Модель расчета учитывает специфику ML-систем, которую обучающиеся часто
упускают:
  * не все обращения обрабатываются автоматически — часть уходит на ручную
    проверку из-за низкой уверенности модели;
  * ошибки модели имеют стоимость (ложные срабатывания требуют исправления);
  * помимо разработки есть периодические затраты: инференс, мониторинг,
    переобучение при деградации качества.

Запуск:
    python tools/ai_project_economics.py --demo
    python tools/ai_project_economics.py --volume 120000 --manual-cost 55 \\
        --accuracy 0.92 --automation-rate 0.7 --capex 3500000 --opex-year 900000
    python tools/ai_project_economics.py --demo --sensitivity accuracy

Скрипт не требует сторонних библиотек.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field


@dataclass
class ProjectParameters:
    """Исходные параметры оценки ИИ-решения."""

    volume_per_year: int          # объем операций в год, шт.
    manual_cost: float            # стоимость ручной обработки одной операции, руб.
    accuracy: float               # доля корректных решений модели, 0..1
    automation_rate: float        # доля операций, обрабатываемых без человека, 0..1
    capex: float                  # единовременные затраты (разработка, внедрение), руб.
    opex_per_year: float          # периодические затраты в год, руб.
    error_cost: float = 0.0       # стоимость исправления одной ошибки модели, руб.
    horizon_years: int = 3        # горизонт оценки, лет
    discount_rate: float = 0.0    # ставка дисконтирования, доли единицы

    def validate(self) -> None:
        if not 0 < self.accuracy <= 1:
            raise ValueError("accuracy должна быть в диапазоне (0; 1]")
        if not 0 <= self.automation_rate <= 1:
            raise ValueError("automation_rate должна быть в диапазоне [0; 1]")
        if self.volume_per_year <= 0:
            raise ValueError("volume_per_year должен быть положительным")
        if self.horizon_years <= 0:
            raise ValueError("horizon_years должен быть положительным")


@dataclass
class EconomicResult:
    """Результаты расчета."""

    baseline_cost: float          # затраты при ручной обработке, руб./год
    automated_volume: float       # объем, обработанный автоматически, шт./год
    residual_manual_cost: float   # затраты на оставшуюся ручную обработку, руб./год
    error_losses: float           # потери от ошибок модели, руб./год
    gross_saving: float           # валовая экономия, руб./год
    net_saving: float             # чистая экономия с учетом OPEX, руб./год
    payback_years: float | None   # срок окупаемости, лет (None — не окупается)
    tco: float                    # совокупная стоимость владения за горизонт, руб.
    npv: float                    # чистая приведенная стоимость, руб.
    roi: float                    # рентабельность инвестиций за горизонт, %
    warnings: list[str] = field(default_factory=list)


def calculate(params: ProjectParameters) -> EconomicResult:
    """Рассчитывает показатели эффективности внедрения ИИ-решения."""
    params.validate()

    baseline_cost = params.volume_per_year * params.manual_cost
    automated_volume = params.volume_per_year * params.automation_rate
    residual_volume = params.volume_per_year - automated_volume
    residual_manual_cost = residual_volume * params.manual_cost

    # ошибки возникают только в автоматически обработанном объеме
    errors_count = automated_volume * (1 - params.accuracy)
    error_losses = errors_count * params.error_cost

    gross_saving = baseline_cost - residual_manual_cost - error_losses
    net_saving = gross_saving - params.opex_per_year

    payback_years = params.capex / net_saving if net_saving > 0 else None

    tco = params.capex + params.opex_per_year * params.horizon_years

    npv = -params.capex
    for year in range(1, params.horizon_years + 1):
        npv += net_saving / ((1 + params.discount_rate) ** year)

    roi = ((net_saving * params.horizon_years - params.capex) / params.capex * 100
           if params.capex else float("inf"))

    warnings: list[str] = []
    if net_saving <= 0:
        warnings.append("чистая экономия неположительна: проект не окупается при данных параметрах")
    if payback_years is not None and payback_years > params.horizon_years:
        warnings.append("срок окупаемости превышает горизонт оценки")
    if params.error_cost == 0:
        warnings.append("стоимость ошибки принята равной нулю — оценка оптимистична")
    if params.accuracy > 0.98:
        warnings.append("заявленная точность выше 0,98 — проверьте реалистичность допущения")

    return EconomicResult(
        baseline_cost=baseline_cost,
        automated_volume=automated_volume,
        residual_manual_cost=residual_manual_cost,
        error_losses=error_losses,
        gross_saving=gross_saving,
        net_saving=net_saving,
        payback_years=payback_years,
        tco=tco,
        npv=npv,
        roi=roi,
        warnings=warnings,
    )


def money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " руб."


def print_result(params: ProjectParameters, result: EconomicResult) -> None:
    print("=" * 62)
    print("ОЦЕНКА ЭКОНОМИЧЕСКОЙ ЭФФЕКТИВНОСТИ ИИ-РЕШЕНИЯ")
    print("=" * 62)
    print("Исходные допущения:")
    print(f"  объем операций в год           {params.volume_per_year:>12,}".replace(",", " "))
    print(f"  стоимость ручной обработки     {money(params.manual_cost):>17}")
    print(f"  точность модели                {params.accuracy:>12.1%}")
    print(f"  доля автоматизации             {params.automation_rate:>12.1%}")
    print(f"  стоимость ошибки               {money(params.error_cost):>17}")
    print(f"  единовременные затраты (CAPEX) {money(params.capex):>17}")
    print(f"  периодические затраты (OPEX)   {money(params.opex_per_year):>17} в год")
    print(f"  горизонт оценки                {params.horizon_years:>12} лет")
    print("-" * 62)
    print("Результаты:")
    print(f"  затраты без ИИ (базовый вариант)   {money(result.baseline_cost):>20} в год")
    print(f"  остаточная ручная обработка        {money(result.residual_manual_cost):>20} в год")
    print(f"  потери от ошибок модели            {money(result.error_losses):>20} в год")
    print(f"  валовая экономия                   {money(result.gross_saving):>20} в год")
    print(f"  чистая экономия (за вычетом OPEX)  {money(result.net_saving):>20} в год")
    payback = f"{result.payback_years:.2f} лет" if result.payback_years else "не окупается"
    print(f"  срок окупаемости                   {payback:>20}")
    print(f"  совокупная стоимость владения      {money(result.tco):>20}")
    print(f"  NPV за горизонт                    {money(result.npv):>20}")
    print(f"  ROI за горизонт                    {result.roi:>19.1f} %")
    if result.warnings:
        print("-" * 62)
        print("Предупреждения:")
        for warning in result.warnings:
            print(f"  ! {warning}")
    print("=" * 62)


def sensitivity(params: ProjectParameters, parameter: str,
                deltas: tuple[float, ...] = (-0.2, -0.1, 0.0, 0.1, 0.2)) -> None:
    """Анализ чувствительности чистой экономии к изменению параметра."""
    print()
    print(f"Анализ чувствительности по параметру «{parameter}»")
    print(f"{'изменение':>12} | {'значение':>12} | {'чистая экономия':>20} | {'окупаемость':>14}")
    print("-" * 66)
    base_value = getattr(params, parameter)
    for delta in deltas:
        value = base_value * (1 + delta)
        if parameter in ("accuracy", "automation_rate"):
            value = min(value, 1.0)
        modified = ProjectParameters(**{**params.__dict__, parameter: value})
        try:
            result = calculate(modified)
        except ValueError:
            continue
        payback = f"{result.payback_years:.2f} лет" if result.payback_years else "нет"
        shown = f"{value:.3f}" if value < 100 else money(value)
        print(f"{delta:>+11.0%} | {shown:>12} | {money(result.net_saving):>20} | {payback:>14}")
    print()
    print("Вывод для обучающихся: сопоставьте разброс результата с точностью,")
    print("с которой вы способны обосновать исходные допущения.")


DEMO = ProjectParameters(
    volume_per_year=120_000,
    manual_cost=55.0,
    accuracy=0.92,
    automation_rate=0.70,
    capex=3_500_000.0,
    opex_per_year=900_000.0,
    error_cost=180.0,
    horizon_years=3,
    discount_rate=0.10,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Расчет экономики ИИ-проекта")
    parser.add_argument("--demo", action="store_true", help="расчет на демонстрационных данных")
    parser.add_argument("--volume", type=int, help="объем операций в год")
    parser.add_argument("--manual-cost", type=float, help="стоимость ручной обработки, руб.")
    parser.add_argument("--accuracy", type=float, help="точность модели, 0..1")
    parser.add_argument("--automation-rate", type=float, help="доля автоматизации, 0..1")
    parser.add_argument("--capex", type=float, help="единовременные затраты, руб.")
    parser.add_argument("--opex-year", type=float, help="периодические затраты в год, руб.")
    parser.add_argument("--error-cost", type=float, default=0.0, help="стоимость ошибки, руб.")
    parser.add_argument("--horizon", type=int, default=3, help="горизонт оценки, лет")
    parser.add_argument("--discount", type=float, default=0.0, help="ставка дисконтирования")
    parser.add_argument("--sensitivity", choices=["accuracy", "automation_rate", "manual_cost",
                                                  "capex", "opex_per_year", "volume_per_year"],
                        help="построить анализ чувствительности по параметру")
    args = parser.parse_args()

    if args.demo or args.volume is None:
        params = DEMO
        if not args.demo:
            print("Параметры не заданы — используются демонстрационные значения.\n")
    else:
        params = ProjectParameters(
            volume_per_year=args.volume,
            manual_cost=args.manual_cost,
            accuracy=args.accuracy,
            automation_rate=args.automation_rate,
            capex=args.capex,
            opex_per_year=args.opex_year,
            error_cost=args.error_cost,
            horizon_years=args.horizon,
            discount_rate=args.discount,
        )

    print_result(params, calculate(params))
    if args.sensitivity:
        sensitivity(params, args.sensitivity)


if __name__ == "__main__":
    main()
