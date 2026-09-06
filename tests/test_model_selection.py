"""The selection metric must be F1, not R2.

evaluate_models originally ranked classifiers by r2_score, a regression
metric. This test pins the intended behaviour: the model with the better
F1 on the held-out set wins.
"""
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from networksecurity.utils.main_utils.utils import evaluate_models


def _toy_data():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 4))
    y = (X[:, 0] + X[:, 1] > 0).astype(int)
    return X[:200], y[:200], X[200:], y[200:]


def test_scores_are_f1_in_zero_one_range():
    X_tr, y_tr, X_te, y_te = _toy_data()
    report = evaluate_models(
        X_tr, y_tr, X_te, y_te,
        models={"logreg": LogisticRegression(max_iter=500)},
        param={"logreg": {}},
    )
    assert 0.0 <= report["logreg"] <= 1.0


def test_a_real_classifier_beats_a_constant_baseline():
    X_tr, y_tr, X_te, y_te = _toy_data()
    report = evaluate_models(
        X_tr, y_tr, X_te, y_te,
        models={
            "logreg": LogisticRegression(max_iter=500),
            "dummy": DummyClassifier(strategy="most_frequent"),
        },
        param={"logreg": {}, "dummy": {}},
    )
    assert report["logreg"] > report["dummy"]
    assert max(report, key=report.get) == "logreg"
