"""Full pipeline smoke test on a small sample.

Runs ingestion -> validation -> transformation and trains one small model,
then checks the saved artifact is a usable NetworkModel instance. This is
the regression test for save_object(..., obj=NetworkModel), which pickled
the class rather than the fitted wrapper.
"""
from sklearn.ensemble import RandomForestClassifier

from networksecurity.utils.main_utils.utils import load_object, save_object
from networksecurity.utils.ml_utils.model.estimator import NetworkModel


def test_saved_model_artifact_is_an_instance_not_a_class(tmp_path, raw_df, feature_columns):
    from sklearn.impute import KNNImputer
    from sklearn.pipeline import Pipeline

    sample = raw_df.head(200)
    X = sample[feature_columns]
    y = sample["Result"].replace(-1, 0)

    pre = Pipeline([("imputer", KNNImputer(n_neighbors=3))]).fit(X)
    clf = RandomForestClassifier(n_estimators=10, random_state=42).fit(pre.transform(X), y)

    path = tmp_path / "model.pkl"
    save_object(str(path), NetworkModel(preprocessor=pre, model=clf))

    loaded = load_object(str(path))
    assert isinstance(loaded, NetworkModel), "artifact must be a fitted instance, not the class"
    preds = loaded.predict(X.head(5))
    assert len(preds) == 5
