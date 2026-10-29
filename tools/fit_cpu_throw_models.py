"""
Fit the ActionEvaluator's shot success and pass completion models (logistic with quadratic terms, unscaled
coefficients for config.py action_evaluator_kwargs) from tools/collect_cpu_throws.py output, and print the
cross-validated log loss and calibration.

usage: python tools/fit_cpu_throw_models.py <throws.csv>
"""
import csv, json, sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict

CLIP = 3.0
rows = list(csv.DictReader(open(sys.argv[1], encoding='utf-8')))


def log_loss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def features(base_values, names):
    """Same feature definitions as ActionEvaluator._fitted_probability."""
    m = base_values['time_margin']
    out = []
    for name in names:
        if name in base_values:
            out.append(base_values[name])
        elif name == 'time_margin_pos':
            out.append(max(m, 0.0))
        elif name == 'margin_capped':
            out.append(1.0 if m >= CLIP - 1e-9 else 0.0)
        elif name.endswith('_sq'):
            out.append(base_values[name[:-3]] ** 2)
        elif name.startswith('time_margin_x_'):
            out.append(m * base_values[name[len('time_margin_x_'):]])
    return out


for kind, base in (('shot', ['time_margin', 'distance', 'sin_angle']), ('pass', ['time_margin', 'distance', 'catch_time', 'strength_ratio'])):
    names = list(base) + ['time_margin_sq', 'time_margin_pos', 'margin_capped']
    for name in base[1:]:
        names += [name + '_sq', 'time_margin_x_' + name]
    data = [r for r in rows if r['kind'] == kind and r['time_margin'] not in ('', 'None')]
    y = np.array([int(r['success']) for r in data])
    X = []
    for r in data:
        values = {name: float(r[name] or 0) for name in base}
        values['time_margin'] = max(-CLIP, min(CLIP, values['time_margin']))
        X.append(features(values, names))
    X = np.array(X)
    model = LogisticRegression(C=100.0, max_iter=20000, tol=1e-8)
    p = cross_val_predict(model, X, y, cv=5, method='predict_proba')[:, 1]
    model.fit(X, y)
    print(f'\n== {kind}: CV log loss {log_loss(y, p):.4f} (constant {log_loss(y, np.full(len(y), y.mean())):.4f})')
    for low in np.arange(0, 1, 0.1):
        mask = (p >= low) & (p < low + 0.1 + (1e-9 if low >= 0.9 else 0))
        if mask.sum():
            print(f'    predicted {low:.1f}-{low + 0.1:.1f}: actual {y[mask].mean():.2f}  n={mask.sum()}')
    coefficients = {'intercept': round(float(model.intercept_[0]), 5)}
    coefficients.update({name: round(float(c), 5) for name, c in zip(names, model.coef_[0])})
    print(f'{kind} model =', json.dumps(coefficients))
