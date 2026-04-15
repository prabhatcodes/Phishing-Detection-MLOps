# Phishing Detection MLOps Pipeline

An end-to-end machine learning pipeline to detect phishing websites using network security data. Built with a modular MLOps architecture covering data ingestion, validation, transformation, model training, experiment tracking, and cloud deployment.

---

## Project Architecture

```
MongoDB Atlas → Data Ingestion → Data Validation → Data Transformation → Model Trainer → FastAPI → AWS EC2
```

The pipeline is broken into independent components, each producing versioned artifacts, making it easy to debug, retrain, and redeploy.

---

## Tech Stack

| Layer               | Tools                                               |
| ------------------- | --------------------------------------------------- |
| Data Source         | MongoDB Atlas                                       |
| ML                  | Scikit-learn, KNN Imputer, SMOTETomek, RobustScaler |
| Experiment Tracking | MLflow, DagsHub                                     |
| API                 | FastAPI, Uvicorn                                    |
| Containerization    | Docker                                              |
| CI/CD               | GitHub Actions                                      |
| Cloud               | AWS ECR, AWS EC2                                    |

---

## Pipeline Components

**1. Data Ingestion**

- Pulls phishing network data from MongoDB Atlas
- Exports to feature store as raw CSV
- Splits into train/test sets with configurable ratio

**2. Data Validation**

- Validates schema — number of columns, data types
- Detects data drift using Evidently
- Generates drift report as YAML artifact

**3. Data Transformation**

- Handles missing values with KNN Imputer
- Scales features using RobustScaler
- Balances class imbalance using SMOTETomek
- Saves preprocessor as `preprocessing.pkl`

**4. Model Trainer**

- Trains and evaluates 5 classifiers: Random Forest, Gradient Boosting, Decision Tree, AdaBoost, Logistic Regression
- Hyperparameter tuning with GridSearchCV
- Selects best model by F1 score
- Tracks all experiments and metrics with MLflow

**5. FastAPI App**

- `/train` — triggers full training pipeline
- `/predict` — accepts CSV upload, returns predictions as HTML table

---

## Local Setup

```bash
# Clone the repo
git clone https://github.com/prabhatcodes/Phishing-Detection-MLOps.git
cd phishing-detection-pipeline

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export MONGODB_URL_KEY="your_mongodb_connection_string"
export MLFLOW_TRACKING_URI="your_dagshub_mlflow_uri"
export MLFLOW_TRACKING_USERNAME="your_dagshub_username"
export MLFLOW_TRACKING_PASSWORD="your_dagshub_token"

# Run the app
python app.py
```

---

## Docker

```bash
docker build -t phishing-detection .
docker run -p 8080:8080 phishing-detection
```

---

## CI/CD Pipeline

Automated via GitHub Actions on every push to `main`:

1. **CI** — lint and test
2. **CD** — builds Docker image, pushes to AWS ECR
3. **Deploy** — pulls latest image on self-hosted EC2 runner and restarts container

### Required GitHub Secrets

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION
AWS_ECR_LOGIN_URI
ECR_REPOSITORY_NAME
MONGODB_URL_KEY
MLFLOW_TRACKING_URI
MLFLOW_TRACKING_USERNAME
MLFLOW_TRACKING_PASSWORD
```

---

## Project Structure

```
├── networksecurity/
│   ├── components/          # Pipeline stage implementations
│   ├── entity/              # Config and artifact dataclasses
│   ├── pipeline/            # Training and batch prediction pipelines
│   ├── utils/               # ML utilities, metrics, model estimator
│   ├── exception/           # Custom exception handler
│   └── logging/             # Logger module
├── data_schema/             # Schema YAML for validation
├── app.py                   # FastAPI application
├── main.py                  # Pipeline entry point
├── Dockerfile
└── .github/workflows/       # CI/CD pipeline
```

---

## Author

**Prabhat Singh Tomar** — [LinkedIn](https://www.linkedin.com/in/prabhat-singh-tomar/)
