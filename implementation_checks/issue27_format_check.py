"""Compare GUI time labels with independent Decimal/Fraction arithmetic."""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.set_int_max_str_digits(25000)


def oracle(value):
    ratio = Fraction(str(value).strip())
    assert ratio >= 0
    if not ratio:
        return '0', False
    with localcontext() as context:
        context.prec = max(80, len(str(ratio.numerator)) + len(str(ratio.denominator)) + 30)
        number = Decimal(ratio.numerator) / Decimal(ratio.denominator)
        ordinary = Fraction(1, 1000) <= ratio < 10**9
        places = -3 if ordinary else number.adjusted() - 5
        rounded = number.quantize(Decimal(1).scaleb(places), rounding=ROUND_HALF_UP)
        if Decimal('0.001') <= rounded < Decimal('1e9'):
            text = format(rounded, 'f').rstrip('0').rstrip('.') if rounded.as_tuple().exponent < 0 else format(rounded, 'f')
        else:
            exponent = rounded.adjusted()
            mantissa = format(rounded.scaleb(-exponent), 'f').rstrip('0').rstrip('.')
            text = mantissa + 'e' + str(exponent)
        inexact = Fraction(rounded) != ratio
        return ('≈' if inexact else '') + text, inexact


def run(output):
    cases = [
        ('reported fraction', '127500000000000017/2500000000000000'),
        ('zero', '0'), ('negative zero', '-0.000'), ('signed zero', '+0'),
        ('half seconds', '5/2'), ('third', '1/3'), ('microsecond', '0.000001'),
        ('positive tiny decimal', '0.00000001'), ('tiny rational', '1/3000000000000'),
        ('huge exact integer', '9007199254740993'),
        ('ordinary lower bound', '0.001'), ('ordinary upper bound', '1000000000'),
        ('decimal halfway down', '1.234499999999999999999'), ('decimal half tie', '1.2345'),
        ('decimal halfway up', '1.234500000000000000001'),
        ('carry to scientific', '999999999.9995'), ('before scientific carry', '999999999.999499999'),
        ('tiny carry to ordinary', '0.0009999995'), ('before tiny carry', '0.0009999994999999'),
        ('scientific carry', '99999950000'), ('scientific carry tiny', '0.000009999995'),
        ('arbitrary rational above float capacity', f'{10**450 + 10**430}/{10**449 + 17}'),
        ('equal enormous components', f'{10**700 + 19}/{10**700 + 19}'),
        ('extreme small', '1e-9999'), ('extreme large', '1e9999'),
        ('leading decimal', '.25'), ('trailing decimal', '25.'),
        ('signed exponent', '+2.5e+3'), ('leading zeros', '0002.5000'),
        ('whitespace retained', '  1/3  '),
        ('same rounded label A', '51.0000001'), ('same rounded label B', '51.0000002'),
    ]
    rng = random.Random(27)
    for index in range(500):
        digits = rng.randint(1, 150)
        numerator = rng.randrange(1, 10**digits)
        denominator = rng.randrange(1, 10**rng.randint(1, 150))
        cases.append((f'random ratio {index}', f'{numerator}/{denominator}'))
    invalid = [None, True, False, {}, [], '', ' ', 'NaN', 'Infinity', '-Infinity', '1/0',
               '-1', '-1/2', '-.001', '1/-2', '1/2/3', '1e', '1e100000', '1,000', '1_000']
    numeric = [(0, '0'), (2.5, '2.5'), (1e-8, '1e-8'), (1e20, '100000000000000000000')]
    inputs = [value for _, value in cases] + invalid + [value for value, _ in numeric]
    executed = subprocess.run([str(ROOT / '.runtimeenv/bin/node'), str(Path(__file__).with_suffix('.cjs'))],
                              input=json.dumps(inputs), text=True, capture_output=True, check=True)
    actual = json.loads(executed.stdout)
    checked = []
    for (name, value), result in zip(cases, actual):
        label, rounded = oracle(value)
        assert result == {'label': label, 'exact': value, 'rounded': rounded, 'valid': True}, (name, value, result, label)
        displayed = Fraction(result['label'].removeprefix('≈'))
        assert displayed > 0 or Fraction(value) == 0, (name, 'positive value displayed as zero')
        if Fraction(1, 1000) <= Fraction(value) < 10**9:
            assert abs(displayed-Fraction(value)) <= Fraction(1, 2000), name
        checked.append({'name': name, 'input': value, **result})
    for value, result in zip(invalid, actual[len(cases):len(cases)+len(invalid)]):
        assert result['label'] == 'Time unavailable' and not result['valid'] and not result['rounded'], (value, result)
    for (_, exact), result in zip(numeric, actual[len(cases)+len(invalid):]):
        label, rounded = oracle(exact)
        assert result == {'label': label, 'exact': exact, 'rounded': rounded, 'valid': True}, (exact, result)
    assert actual[30]['label'] == actual[31]['label'] and actual[30]['exact'] != actual[31]['exact']
    report = {'passed': True, 'valid_cases': len(cases), 'invalid_cases': len(invalid), 'numeric_cases': len(numeric),
              'independent_oracle': 'Python Decimal ROUND_HALF_UP with Fraction value comparison',
              'ordinary_display_error_bound_seconds': '1/2000', 'cases': checked,
              'invalid_inputs': invalid, 'limitations': 'Pure formatting only; real components and navigation are verified by separate browser checks.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'passed': True, 'valid_cases': len(cases), 'invalid_cases': len(invalid), 'numeric_cases': len(numeric), 'report': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
