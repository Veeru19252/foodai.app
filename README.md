<div align="center">

# 🍔 FoodAI

### AI-Powered Food Delivery Platform

A Swiggy-style food delivery platform with **real-time tracking** and **machine learning** — delivery-time (ETA) prediction and zone-wise demand forecasting.

![Python](https://img.shields.io/badge/Python-3.10-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-UI-red) ![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green) ![XGBoost](https://img.shields.io/badge/XGBoost-ML-orange) ![SQLite](https://img.shields.io/badge/SQLite-DB-lightgrey) ![License](https://img.shields.io/badge/License-MIT-yellow)

**Status:** 🚧 In Development · **Team:** 2 People

</div>

---

## 📑 Table of Contents

- [Features](#-features)
- [Demo](#-demo)
- [Screenshots](#-screenshots)
- [Tech Stack](#-tech-stack)
- [Architecture](#-architecture)
- [Project Structure](#-project-structure)
- [Installation](#-installation)
- [Usage](#-usage)
- [API Documentation](#-api-documentation)
- [Configuration](#-configuration)
- [Dataset](#-dataset)
- [Model Information](#-model-information)
- [Algorithms Used](#-algorithms-used)
- [Folder Structure](#-folder-structure)
- [Testing](#-testing)
- [Performance Metrics](#-performance-metrics)
- [Roadmap](#-roadmap)
- [Future Improvements](#-future-improvements)
- [Challenges Faced](#-challenges-faced)
- [Lessons Learned](#-lessons-learned)
- [Contributing](#-contributing)
- [License](#-license)
- [Authors](#-authors)
- [Acknowledgements](#-acknowledgements)

---

## ✨ Features

### 🖥️ Platform
- **4 roles** — Customer · Restaurant · Delivery Partner · Admin
- **Customer signup** — register a new account from the login page
- **Full order flow** — browse restaurants → menu → cart → checkout → live status tracking
- **Live order tracking** — simulated delivery GPS moving on a map
- **Restaurant panel** — accept/reject orders, manage menu
- **Admin dashboard** — revenue, order analytics, demand heatmap

### 🧠 AI / ML
- **ETA prediction (XGBoost)** — predicts delivery time in minutes; beats the simple distance-based baseline
- **Demand forecasting** — predicts orders per zone for the next hour; drives the admin heatmap + driver pre-positioning
- **Rigorous evaluation** — baseline vs ML comparison tables (MAE / RMSE / MAPE)

---

## 🎥 Demo

🔗 **Live Demo:** *[Add your Hugging Face Spaces URL here after deployment (Week 9)]*

📹 **Demo Video:** *[Add your YouTube demo link here]*

> **Quick demo script:** Login as `customer@foodai.com` → order from "Spice Garden" → watch the delivery partner move live on the map → see the AI-predicted ETA update.

> **Admin demo script:** Login as `admin@foodai.com` / `password123` → Admin Dashboard shows Today Revenue, Total Orders, Active Orders and Avg Order Value metric cards → plotly charts (orders per day, revenue trend, orders per restaurant, top-selling items) → demand heatmap with zone circles colored green (<2) / yellow (2-4) / orange (4-6) / red (>6) by forecast_service predicted orders → recent orders table. The heatmap uses the XGBoost demand model with a moving-average fallback.

> **Register:** The login page has a Register tab — create a customer account (name, email, password) and log in immediately.

---

## 📸 Screenshots

*[Add screenshots here — recommended: ① Restaurant listing ② Menu + cart ③ Live tracking map ④ Admin Dashboard (metric cards + heatmap)]*

```
① Restaurant Listing    ② Menu & Cart       ③ Live Tracking        ④ Admin Dashboard (metric cards + heatmap)
[placeholder]           [placeholder]        [placeholder]          [placeholder]
```

---

## 🧱 Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | **Streamlit** | Python-only UI — no JavaScript needed |
| Backend | **FastAPI** | Modern REST API framework |
| Database | **SQLite** | Simple, zero-config, perfect for the semester |
| ML | **pandas · scikit-learn · XGBoost** | Beginner-friendly + powerful gradient boosting |
| Model Saving | **joblib** | Load models in the app |
| Maps | **folium + streamlit-folium** | Free interactive maps |
| Real-time | **streamlit-autorefresh** | Polling every 2s (simulates live tracking) |
| Deployment | **Hugging Face Spaces** | Free Streamlit hosting |

---

## 🏗️ Architecture

```
┌────────────┐     ┌─────────────┐     ┌──────────────┐
│  Streamlit │────▶│   FastAPI   │────▶│    SQLite    │
│   (UI)     │     │  (backend)  │     │  (database)  │
└────────────┘     └──────┬──────┘     └──────────────┘
                          │
                    ┌─────▼──────┐
                    │  ML Models │   eta_model.joblib
                    │  (XGBoost) │   forecast_model.joblib
                    └────────────┘
```

**Data flow:**
1. Customer places order → saved in SQLite with features (distance, hour, zone, prep time)
2. Person B's pipeline trains XGBoost on order history
3. The app loads the saved model and predicts ETA live during tracking
4. Admin dashboard renders the demand forecast heatmap

---

## 🗂️ Project Structure

```
foodai/
├── app.py              # Streamlit frontend entry point
├── database.py         # SQLite schema + query helpers
├── seed_data.py        # Demo data (5 restaurants, 25 items, 8 users)
├── requirements.txt    # All dependencies
├── README.md           # This file
```

---

## 🚀 Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/foodai.git
cd foodai

# 2. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## 💻 Usage

```bash
# Start the app (creates + seeds the database automatically on first run)
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

### 🔑 Demo Logins

| Role | Email | Password |
|---|---|---|
| Customer | `customer@foodai.com` | `password123` |
| Restaurant | `spice@foodai.com` | `password123` |
| Delivery | `rider@foodai.com` | `password123` |
| Admin | `admin@foodai.com` | `password123` |

---

## 📡 API Documentation

> FastAPI endpoints (expanding as the project grows)

### `GET /restaurants`
Return all restaurants sorted by rating.

**Response:**
```json
[
  { "id": 1, "name": "Spice Garden", "cuisine": "North Indian", "rating": 4.0, "address": "MG Road" }
]
```

### `GET /restaurants/{id}/menu`
Return the menu for one restaurant.

### `POST /orders`
Create an order.

**Request body:**
```json
{
  "customer_id": 1,
  "restaurant_id": 1,
  "items": [
    { "menu_item_id": 1, "quantity": 2, "price": 220.0 }
  ]
}
```

**Response:**
```json
{ "order_id": 1, "status": "PLACED", "total": 440.0 }
```

### `PATCH /orders/{id}/status`
Update an order's status (`PLACED → CONFIRMED → PREPARING → OUT_FOR_DELIVERY → DELIVERED`).

---

## ⚙️ Configuration

All configuration lives at the top of the source files (no `.env` needed for the starter):

| Setting | Location | Default |
|---|---|---|
| Database path | `database.py` → `DB_PATH` | `foodai.db` (next to project) |
| Auto-refresh interval | `app.py` (live tracking) | 2 seconds |
| Random seed (ML) | Person B notebooks | `random_state=42` |
| Model files | `models/` | `eta_model.joblib` |

---

## 📊 Dataset

### Source
- **Simulated order data** generated by `simulate_orders.py` (Person B, Week 4–5)
- 500+ realistic orders with features: distance (via OSRM API), prep time, hour-of-day, zone, traffic factor, actual delivery minutes
- *(Optionally validated against the public* [Food Delivery Dataset](https://www.kaggle.com/datasets/gauravmalik26/food-delivery-dataset) *on Kaggle)*

### Why simulated?
- Real company data isn't public; simulated data lets us control quality and prove the full pipeline
- Documented honestly in the report (limitation + future work)

---

## 🤖 Model Information

### Model 1: ETA Prediction (Regression)
| Field | Value |
|---|---|
| Algorithm | XGBoost (`XGBRegressor`) |
| Target | Delivery time (minutes) |
| Features | distance_km, prep_time_min, hour_of_day, day_of_week, zone (one-hot), is_weekend |
| Evaluation | MAE, RMSE |
| Model file | `models/eta_model.joblib` |

### Model 2: Demand Forecasting (Time-Series)
| Field | Value |
|---|---|
| Algorithm | XGBoost on lag features |
| Target | Orders per zone per hour |
| Features | hour, weekday, prev_1h, prev_3h_avg |
| Evaluation | RMSE, MAPE |
| Output | Admin heatmap data |

---

## 🧮 Algorithms Used

| Algorithm | Type | Where |
|---|---|---|
| **XGBoost** (gradient boosting) | Ensemble regression | ⭐ Main ETA + forecast model |
| Random Forest | Ensemble baseline | Compared model |
| Linear Regression | Statistical baseline | Compared model |
| Moving Average | Time-series baseline | Forecast baseline |
| GridSearchCV | Hyperparameter tuning | Best model selection |
| Cross-validation | Evaluation | Reliable metrics |
| One-hot encoding | Preprocessing | Categorical features |
| SHAP (planned) | Explainability | Model interpretation |

---

## 📂 Folder Structure

```
foodai/
├── app.py                  # Streamlit frontend
├── database.py             # SQLite schema + queries
├── seed_data.py            # Demo seed data
├── requirements.txt        # Dependencies
├── notebooks/              # (Person B) ML experiments
│   ├── 01_pandas_practice.ipynb
│   ├── 02_first_models.ipynb
│   ├── 03_order_simulator.ipynb
│   ├── 04_eta_model.ipynb
│   └── 05_demand_forecast.ipynb
├── data/                   # (Person B) datasets
│   ├── orders.csv
│   └── forecast_data.csv
├── models/                 # (Person B) saved models
│   ├── eta_model.joblib
│   └── forecast_model.joblib
├── scripts/                # (Person B) reusable scripts
│   ├── simulate_orders.py
│   ├── train_eta.py
│   ├── predict_eta.py
│   └── forecast.py
└── outputs/                # (Person B) charts + tables
    ├── metrics_eta.json
    └── charts/
        ├── eta_metrics_comparison.png
        ├── eta_feature_importance.png
        └── eta_actual_vs_predicted.png
```

---

## 🧪 Testing

> Planned testing strategy (adds marks — most students skip this)

| Test Type | What | Tool |
|---|---|---|
| Unit tests (database) | CRUD operations work | `pytest` |
| Unit tests (API) | Endpoints return correct JSON | `pytest` + `httpx` |
| End-to-end | Login → order → status flow | Manual script |
| Load test | 100 concurrent orders survive | Custom script + `streamlit-autorefresh` |
| ML validation | Test set never touched until final | Holdout set |

```bash
# Run tests (Week 9)
pytest tests/
```

---

## 📈 Performance Metrics

### ETA Prediction
| Model | MAE (min) | RMSE |
|---|---|---|
| Baseline (distance ÷ 20 km/h) | 2.84 | 3.63 |
| Linear Regression | 1.93 | 2.47 |
| Random Forest | 1.65 | 2.00 |
| **XGBoost** | **2.03** | **2.61** |

*XGBoost is our deployed model (beats baseline by ~28%); Random Forest performed slightly better on this small simulated dataset.*

**Retrain the ETA model:** `.venv/bin/python scripts/train_eta.py`

### Demand Forecasting
| Model | RMSE (orders/hr/zone) | MAPE |
|---|---|---|
| Moving average | 0.76 | 40.4% |
| **XGBoost** | **0.66** | **32.9%** |

*XGBoost beats the moving-average baseline by ~18% lower MAPE.*

**Model artifacts:** `models/forecast_model.joblib`, `models/forecast_meta.json`, `outputs/metrics_forecast.json`, `outputs/charts/forecast_*.png`

**Retrain the forecast model:** `.venv/bin/python scripts/train_forecast.py`

---

## 🗓️ Roadmap

| Phase | Weeks | Deliverable | Status |
|---|---|---|---|
| Learning | 0–3 | Python, pandas, ML, Streamlit basics | ✅ |
| Platform core | 4–5 | Auth, restaurants, cart, checkout, order flow | ✅ |
| Live tracking | 6 | Map + simulated GPS | ✅ |
| **ML #1: ETA** | 7 | XGBoost ETA beats baseline | ✅ |
| **ML #2: Forecasting** | 8 | Heatmap + comparison table | ✅ |
| Admin + deploy | 9 | ✅ Admin dashboard · ✅ Customer signup/register · ☐ Hugging Face Spaces · ☐ demo video | ✅ done (deploy pending) |

---

## 🔮 Future Improvements

- [ ] **Hugging Face Spaces deployment** — host the app on free Streamlit hosting
- [ ] **Demo video** — record a walkthrough for the final submission
- [ ] **WebSockets** instead of polling — true real-time tracking
- [ ] **Real GPS tracking** — replace simulated GPS with actual device location
- [ ] **Real payment** integration (Razorpay test mode)
- [ ] **Real open dataset** training (Kaggle food delivery data)
- [ ] **More features**: traffic-aware ETA, weather data
- [ ] **LSTM / DeepAR** for forecasting (beyond XGBoost)
- [ ] **Mobile-friendly UI** or PWA
- [ ] **Notifications** (email/WhatsApp-style logs)
- [ ] **SHAP explainability** in the demo

---

## 🧗 Challenges Faced

> Update this as you go — examiners love honesty.

- **Real-time tracking in Streamlit** → solved with `streamlit-autorefresh` polling (documented trade-off vs WebSockets)
- **Class imbalance / data realism** → improved with realistic traffic factors in the simulator
- **Overfitting in ETA model** → controlled via cross-validation + GridSearchCV
- *[Add more as you hit them]*

---

## 💡 Lessons Learned

> Write 3–5 after the project — these go straight into your viva answers.

- Record baselines **before** building ML — otherwise you can't prove improvement
- Data quality matters more than model choice
- Splitting data before preprocessing prevents silent data leakage
- Simple working app > fancy broken features
- Team merges at checkpoints beat everyone coding at the end

---

## 🤝 Contributing

This is a semester project, but contributions are welcome:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-idea`)
3. Commit changes (`git commit -m 'Add amazing idea'`)
4. Push (`git push origin feature/amazing-idea`)
5. Open a Pull Request

---

## 📝 License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

## 👥 Authors

| Name | Role | Work |
|---|---|---|
| **Person A** | Web Developer | Streamlit, FastAPI, SQLite, live tracking, deployment |
| **Person B** | AI/ML Engineer | Data pipeline, XGBoost ETA, demand forecasting |

---

## 🙏 Acknowledgements

- **Swiggy / Zomato engineering blogs** — inspiration for ETA + forecasting approaches
- **StatQuest (Josh Starmer)** — ML concepts made clear
- **Data Professor** — Streamlit tutorials
- **Kaggle** — free courses + practice datasets
- **XGBoost paper** (Chen & Guestrin, 2016) — the model we built on
- **fastapi.tiangolo.com** — excellent FastAPI docs
