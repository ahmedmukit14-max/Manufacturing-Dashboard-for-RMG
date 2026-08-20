import os
import math
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient

app = FastAPI()

# CORS – allow your Vercel frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict to your Vercel URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB – read URI from environment variable
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable not set")
client = MongoClient(MONGO_URI)
db = client["dgl_db"]          # confirmed
collection = db["monthly_records"]

def clean_nan(obj):
    if isinstance(obj, list):
        return [clean_nan(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj

@app.get("/")
def root():
    return {"message": "DGL Dashboard API is running"}

@app.get("/monthly-records")
def get_monthly_records():
    records = list(collection.find({}, {"_id": 0}))
    return clean_nan(records)

# ---------- Aggregated dashboard data ----------
MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

def month_sort_key(label):
    m = str(label).strip()
    parts = m.split('-')
    if len(parts) == 2:
        mi = MONTH_NAMES.index(parts[0][:3].capitalize()) if parts[0][:3].capitalize() in MONTH_NAMES else 0
        yr = int(parts[1]) if parts[1].isdigit() else 0
        return yr * 12 + mi
    return 0

def num(v):
    try:
        return float(v)
    except:
        return 0.0

def mean(arr):
    return sum(arr) / len(arr) if arr else 0

def round1(v):
    return round(v, 1)

def round2(v):
    return round(v, 2)

@app.get("/dashboard-data")
def get_dashboard_data():
    # Fetch all records
    rows = list(collection.find({}, {"_id": 0}))
    if not rows:
        return {"error": "No data found in collection"}

    # Ensure numeric fields
    for r in rows:
        for k, v in r.items():
            if k not in ["Month", "Plant"]:
                r[k] = num(v)

    # Months sorted
    months = sorted(set(r["Month"] for r in rows), key=month_sort_key)
    latest = months[-1]
    prev = months[-2] if len(months) > 1 else latest

    latest_rows = [r for r in rows if r["Month"] == latest]
    prev_rows = [r for r in rows if r["Month"] == prev]

    def overall_avg(key, pct=True):
        vals = [r[key] for r in rows if key in r]
        return round1(mean(vals) * (100 if pct else 1))

    def latest_avg(key, pct=True):
        vals = [r[key] for r in latest_rows if key in r]
        return round1(mean(vals) * (100 if pct else 1))

    def prev_avg(key, pct=True):
        vals = [r[key] for r in prev_rows if key in r]
        return round1(mean(vals) * (100 if pct else 1))

    # Header
    header = {
        "company": "DEKKOISHO GROUP MANUFACTURING",
        "view": f"Consolidated View ({len(set(r['Plant'] for r in rows))} Units)",
        "month": f"{months[0]} – {latest} (YTD)"
    }

    # KPIs
    kpis = {
        "efficiency": {
            "label": "Efficiency %",
            "value": latest_avg("Efficiency"),
            "unit": "%",
            "lastMonth": prev_avg("Efficiency"),
            "extra": f"YTD Avg: {overall_avg('Efficiency')}%",
            "accent": "green"
        },
        "brands": {
            "label": "Brand/Buyer Mix %",
            "value": latest_avg("No. of Brands/Buyers Handled"),
            "unit": "%",
            "lastMonth": prev_avg("No. of Brands/Buyers Handled"),
            "extra": f"YTD Avg: {overall_avg('No. of Brands/Buyers Handled')}%",
            "accent": "amber"
        },
        "styleChange": {
            "label": "Style Change Over/Line",
            "value": round1(mean([r["Style Change Over/Line"] for r in latest_rows if "Style Change Over/Line" in r])),
            "unit": "",
            "lastMonth": round1(mean([r["Style Change Over/Line"] for r in prev_rows if "Style Change Over/Line" in r])),
            "extra": f"YTD Avg: {round1(mean([r['Style Change Over/Line'] for r in rows if 'Style Change Over/Line' in r]))}",
            "accent": "teal"
        },
        "cutToShip": {
            "label": "Cut-to-Ship Ratio",
            "value": round2(mean([r["Cut-to-Ship Ratio"] for r in latest_rows if "Cut-to-Ship Ratio" in r])),
            "unit": "",
            "lastMonth": round2(mean([r["Cut-to-Ship Ratio"] for r in prev_rows if "Cut-to-Ship Ratio" in r])),
            "extra": f"YTD Avg: {round2(mean([r['Cut-to-Ship Ratio'] for r in rows if 'Cut-to-Ship Ratio' in r]))}",
            "accent": "amber"
        },
        "shortShipment": {
            "label": "(-) Short Shipment",
            "value": latest_avg("(-) Short Shipment"),
            "unit": "%",
            "lastMonth": prev_avg("(-) Short Shipment"),
            "extra": f"YTD Avg: {overall_avg('(-) Short Shipment')}%",
            "accent": "rose"
        },
        "planAchievement": {
            "label": "Plan Achievement",
            "value": latest_avg("Plan Achievement"),
            "unit": "%",
            "hero": True,
            "accent": "green",
            "extra": f"YTD Avg: {overall_avg('Plan Achievement')}% · vs. production plan"
        },
        "productivity": {
            "label": "Productivity Surplus",
            "value": latest_avg("Productivity- CM Surplus/(Deficit)"),
            "unit": "%",
            "hero": True,
            "accent": "violet",
            "extra": f"YTD Avg: {overall_avg('Productivity- CM Surplus/(Deficit)')}% · CM surplus/deficit"
        }
    }

    # Efficiency trend
    efficiency_trend = []
    cum = []
    for m in months:
        m_rows = [r for r in rows if r["Month"] == m]
        monthly = round1(mean([r["Efficiency"] for r in m_rows]) * 100)
        cum.extend([r["Efficiency"] for r in m_rows])
        ytd = round1(mean(cum) * 100)
        efficiency_trend.append({
            "month": m,
            "monthly": monthly,
            "ytd": ytd,
            "target": 65   # fixed target
        })

    # Gauges
    gauges = {
        "firstTimeInspection": {
            "label": "First Time Inspection Pass Rate",
            "value": overall_avg("First Time Inspection Pass Rate"),
            "target": 95,
            "max": 100
        },
        "onTimeShipment": {
            "label": "On Time Shipment %",
            "value": overall_avg("On Time Shipment %"),
            "target": 98,
            "max": 100
        },
        "operatingMargin": {
            "label": "Operating Margin (EBITDA)",
            "value": overall_avg("Operating Margin (EBITDA)"),
            "target": 12,
            "max": 20
        },
        "otdf": {
            "label": "OTDF %",
            "value": overall_avg("OTDF"),
            "target": 95,
            "max": 100
        }
    }

    # DHU breakdown
    dhu = [
        {"label": "Sewing", "value": overall_avg("Sewing DHU%"), "color": "#4A7BD9"},
        {"label": "Cutting", "value": overall_avg("Cutting DHU %"), "color": "#F5B84D"},
        {"label": "Finishing", "value": overall_avg("Finishing DHU %"), "color": "#8C7CF6"}
    ]

    # Minutes chart
    minutes_chart = []
    for m in months:
        m_rows = [r for r in rows if r["Month"] == m]
        minutes_chart.append({
            "month": m,
            "earned": round1(sum(r["Earned Minutes"] for r in m_rows) / 1e6),
            "available": round1(sum(r["Available Minutes"] for r in m_rows) / 1e6)
        })

    # Unit breakdown
    plants = sorted(set(r["Plant"] for r in rows))
    total_earned = sum(r["Earned Minutes"] for r in rows)
    units = []
    for p in plants:
        p_rows = [r for r in rows if r["Plant"] == p]
        units.append({
            "unit": p,
            "styleChangeOverLine": round2(mean([r["Style Change Over/Line"] for r in p_rows if "Style Change Over/Line" in r])),
            "productionShare": round1(sum(r["Earned Minutes"] for r in p_rows) / total_earned * 100),
            "efficiency": round1(mean([r["Efficiency"] for r in p_rows]) * 100),
            "dhu": round2((mean([r["Sewing DHU%"] for r in p_rows]) +
                           mean([r["Cutting DHU %"] for r in p_rows]) +
                           mean([r["Finishing DHU %"] for r in p_rows])) * 100),
            "otdf": round1(mean([r["OTDF"] for r in p_rows]) * 100)
        })

    result = {
        "header": header,
        "kpis": kpis,
        "efficiencyTrend": efficiency_trend,
        "gauges": gauges,
        "dhu": dhu,
        "minutesChart": minutes_chart,
        "units": units
    }
    return clean_nan(result)