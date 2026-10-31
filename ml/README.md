# NAVIRA ML module

This folder holds the optional TF-IDF and Logistic Regression text-classification model used to triage human-labelled news records. It does not predict crime risk or verify reports. The backend applies privacy filtering, exposes training and prediction endpoints, and records run metadata; model fitting and inference live in `news_classifier.py`.

Install optional dependencies from the repository root with `python -m pip install -r ml/requirements.txt`. Backend-facing functions are provided by `backend/app/services/ml.py`.
