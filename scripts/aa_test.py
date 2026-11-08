"""Measures the false-winner rate: run the real stopping rule on arms with no true difference.

    python scripts/aa_test.py

Uses the production functions from controller.stats, so it tests what actually runs. Data is
synthetic and contains no simulator truth.
"""
import random

from controller import config as cfg
from controller import stats


def one_experiment(rng: random.Random, p: float, arms: int, control_per_day: int, arm_per_day: int, days: int) -> bool:
    n_max = stats.sample_size_per_arm(p, cfg.MDE_RELATIVE, cfg.ALPHA_FAMILY / arms, cfg.POWER)
    x_c = n_c = 0
    x = [0] * arms
    n = [0] * arms
    spent = 0.0
    for day in range(1, days + 1):
        x_c += sum(rng.random() < p for _ in range(control_per_day))
        n_c += control_per_day
        for i in range(arms):
            x[i] += sum(rng.random() < p for _ in range(arm_per_day))
            n[i] += arm_per_day
        info = min(n) / n_max
        elapsed = day / days
        final = day == days or info >= 1
        t = 1.0 if final else max(info, elapsed)
        total = stats.obf_alpha_spent(t, cfg.ALPHA_FAMILY)
        nominal = max(total - spent, 0.0)
        spent = max(total, spent)
        comps = {i: stats.compare_stratified([(x[i], n[i], x_c, n_c)]) for i in range(arms)}
        rejected = stats.holm_rejections({i: c.p_two_sided for i, c in comps.items()}, nominal)
        if any(comps[i].diff > 0 and min(n[i], n_c) >= cfg.MIN_ARM_SAMPLE for i in rejected):
            return True
        if final:
            return False
    return False


def main() -> None:
    rng = random.Random(20270104)
    runs = 3000
    cases = [("3 challengers, renewal-sized traffic, 4 days", 0.55, 3, 630, 210, 4),
             ("2 challengers, renewal-sized traffic, 4 days", 0.55, 2, 630, 315, 4),
             ("3 challengers, load-sized traffic, 2.5 days", 0.55, 3, 2400, 800, 3)]
    print(f"False-winner rate, {runs} A/A experiments per row, family alpha {cfg.ALPHA_FAMILY}, upper tail only\n")
    print("| case | false winners | rate | 95% margin |\n|---|---|---|---|")
    for label, p, arms, control, arm, days in cases:
        hits = sum(one_experiment(rng, p, arms, control, arm, days) for _ in range(runs))
        rate = hits / runs
        print(f"| {label} | {hits} | {rate:.2%} | +/-{1.96 * (rate * (1 - rate) / runs) ** 0.5:.2%} |")


if __name__ == "__main__":
    main()
