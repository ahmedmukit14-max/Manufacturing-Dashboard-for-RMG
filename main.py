import os
from collections import defaultdict
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient

app = FastAPI()

# Enable CORS for your frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or restrict to your Vercel domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. MongoDB Connection ---
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable not set!")

client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client["dgl_db"]
collection = db["monthly_records"]  # adjust if your collection name differs
print("DATABASE:", db.name)
print("COLLECTION:", collection.name)
print("DOCUMENT COUNT:", collection.count_documents({}))

# --- 2. Helpers (same as before) ---
def parse_num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, str):
        v = v.strip().replace(",", "").replace(" ", "")
        if "%" in v:
            v = v.replace("%", "")
            try:
                return float(v) / 100.0
            except ValueError:
                return 0.0
        try:
            return float(v)
        except ValueError:
            return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def get_val(v, to_pct=False):
    n = parse_num(v)
    return n * 100.0 if to_pct else n

def normalize_doc(doc):
    # Nested "No" field handling
    brands = doc.get("No. of Brands/Buyers Handled")
    if brands is None and "No" in doc and isinstance(doc["No"], dict):
        brands = doc["No"].get(" of Brands/Buyers Handled", 0)
    if brands is None:
        brands = 0.0

    return {
        "month": doc.get("Month"),
        "plant": doc.get("Plant"),
        "efficiency": get_val(doc.get("Efficiency"), to_pct=True),
        "brands": get_val(brands, to_pct=True),
        "style_change": get_val(doc.get("Style Change Over/Line"), to_pct=False),
        "cut_to_ship": get_val(doc.get("Cut-to-Ship Ratio"), to_pct=False),
        "short_shipment": get_val(doc.get("(-) Short Shipment"), to_pct=True),
        "first_time_inspection": get_val(doc.get("First Time Inspection Pass Rate"), to_pct=True),
        "on_time_shipment": get_val(doc.get("On Time Shipment %"), to_pct=True),
        "productivity": get_val(doc.get("Productivity- CM Surplus/(Deficit)"), to_pct=True),
        "plan_achievement": get_val(doc.get("Plan Achievement"), to_pct=True),
        "available_minutes": get_val(doc.get("Available Minutes"), to_pct=False),
        "earned_minutes": get_val(doc.get("Earned Minutes"), to_pct=False),
        "sewing_dhu": get_val(doc.get("Sewing DHU%"), to_pct=True),
        "cutting_dhu": get_val(doc.get("Cutting DHU %"), to_pct=True),
        "finishing_dhu": get_val(doc.get("Finishing DHU %"), to_pct=True),
        "operating_margin": get_val(doc.get("Operating Margin (EBITDA)"), to_pct=True),
        "otdf": get_val(doc.get("OTDF"), to_pct=True),
    }

def mean(vals):
    return sum(vals) / len(vals) if vals else 0.0

def sum_vals(vals):
    return sum(vals)


# --- 3. Endpoint ---
@app.get("/dashboard-data")
async def dashboard_data():
    docs = list(collection.find())
    if not docs:
        return {"status": "error", "message": "No data found"}

    rows = [normalize_doc(d) for d in docs]

    # Group by month
    months_data = defaultdict(list)
    for r in rows:
        months_data[r["month"]].append(r)

    # Sort months chronologically
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    def sort_key(month_str):
        parts = month_str.split("-")
        if len(parts) == 2:
            m, y = parts[0], parts[1]
            return (int(y), month_order.index(m[:3]))
        return (0, 0)

    sorted_months = sorted(months_data.keys(), key=sort_key)
    latest_month = sorted_months[-1]
    prev_month = sorted_months[-2] if len(sorted_months) > 1 else latest_month

    latest_rows = months_data[latest_month]
    prev_rows = months_data[prev_month]
    all_rows = rows

    def avg_field(rows_list, field):
        return mean([r[field] for r in rows_list])

    def sum_field(rows_list, field):
        return sum([r[field] for r in rows_list])

    # ---- KPIs ----
    kpis = {
        "efficiency": {
            "label": "Efficiency %",
            "value": round(avg_field(latest_rows, "efficiency"), 1),
            "unit": "%",
            "lastMonth": round(avg_field(prev_rows, "efficiency"), 1),
            "extra": f"YTD Avg: {round(avg_field(all_rows, 'efficiency'), 1)}%",
            "accent": "green"
        },
        "brands": {
            "label": "Brand/Buyer Mix %",
            "value": round(avg_field(latest_rows, "brands"), 1),
            "unit": "%",
            "lastMonth": round(avg_field(prev_rows, "brands"), 1),
            "extra": f"YTD Avg: {round(avg_field(all_rows, 'brands'), 1)}%",
            "accent": "amber"
        },
        "styleChange": {
            "label": "Style Change Over/Line",
            "value": round(avg_field(latest_rows, "style_change"), 2),
            "unit": "",
            "lastMonth": round(avg_field(prev_rows, "style_change"), 2),
            "extra": f"YTD Avg: {round(avg_field(all_rows, 'style_change'), 2)}",
            "accent": "teal"
        },
        "cutToShip": {
            "label": "Cut-to-Ship Ratio",
            "value": round(avg_field(latest_rows, "cut_to_ship"), 2),
            "unit": "",
            "lastMonth": round(avg_field(prev_rows, "cut_to_ship"), 2),
            "extra": f"YTD Avg: {round(avg_field(all_rows, 'cut_to_ship'), 2)}",
            "accent": "amber"
        },
        "shortShipment": {
            "label": "(-) Short Shipment",
            "value": round(avg_field(latest_rows, "short_shipment"), 1),
            "unit": "%",
            "lastMonth": round(avg_field(prev_rows, "short_shipment"), 1),
            "extra": f"YTD Avg: {round(avg_field(all_rows, 'short_shipment'), 1)}%",
            "accent": "rose"
        },
        "planAchievement": {
            "label": "Plan Achievement",
            "value": round(avg_field(latest_rows, "plan_achievement"), 1),
            "unit": "%",
            "hero": True,
            "accent": "green",
            "extra": f"YTD Avg: {round(avg_field(all_rows, 'plan_achievement'), 1)}% · vs. production plan"
        },
        "productivity": {
            "label": "Productivity Surplus",
            "value": round(avg_field(latest_rows, "productivity"), 1),
            "unit": "%",
            "hero": True,
            "accent": "violet",
            "extra": f"YTD Avg: {round(avg_field(all_rows, 'productivity'), 1)}% · CM surplus/deficit"
        }
    }

    # ---- Efficiency Trend ----
    efficiency_trend = []
    cum_eff = []
    for m in sorted_months:
        m_rows = months_data[m]
        monthly_eff = avg_field(m_rows, "efficiency")
        cum_eff.extend([r["efficiency"] for r in m_rows])
        ytd_eff = mean(cum_eff)
        efficiency_trend.append({
            "month": m,
            "monthly": round(monthly_eff, 1),
            "ytd": round(ytd_eff, 1),
            "target": 65.0
        })

    # ---- Gauges ----
    gauges = {
        "firstTimeInspection": {
            "label": "First Time Inspection Pass Rate",
            "value": round(avg_field(all_rows, "first_time_inspection"), 1),
            "target": 95,
            "max": 100
        },
        "onTimeShipment": {
            "label": "On Time Shipment %",
            "value": round(avg_field(all_rows, "on_time_shipment"), 1),
            "target": 98,
            "max": 100
        },
        "operatingMargin": {
            "label": "Operating Margin (EBITDA)",
            "value": round(avg_field(all_rows, "operating_margin"), 1),
            "target": 12,
            "max": 20
        },
        "otdf": {
            "label": "OTDF %",
            "value": round(avg_field(all_rows, "otdf"), 1),
            "target": 95,
            "max": 100
        }
    }

    # ---- DHU ----
    dhu = [
        {"label": "Sewing", "value": round(avg_field(all_rows, "sewing_dhu"), 2), "color": "#4A7BD9"},
        {"label": "Cutting", "value": round(avg_field(all_rows, "cutting_dhu"), 2), "color": "#F5B84D"},
        {"label": "Finishing", "value": round(avg_field(all_rows, "finishing_dhu"), 2), "color": "#8C7CF6"}
    ]

    # ---- Minutes Chart ----
    minutes_chart = []
    for m in sorted_months:
        m_rows = months_data[m]
        earned = sum_field(m_rows, "earned_minutes") / 1_000_000
        available = sum_field(m_rows, "available_minutes") / 1_000_000
        minutes_chart.append({
            "month": m,
            "earned": round(earned, 1),
            "available": round(available, 1)
        })

    # ---- Units ----
    plants_data = defaultdict(list)
    for r in rows:
        plants_data[r["plant"]].append(r)

    total_earned_all = sum_field(all_rows, "earned_minutes")
    units = []
    for plant, p_rows in plants_data.items():
        units.append({
            "unit": plant,
            "styleChangeOverLine": round(avg_field(p_rows, "style_change"), 2),
            "productionShare": round((sum_field(p_rows, "earned_minutes") / total_earned_all) * 100, 1),
            "efficiency": round(avg_field(p_rows, "efficiency"), 1),
            "dhu": round(avg_field(p_rows, "sewing_dhu") + avg_field(p_rows, "cutting_dhu") + avg_field(p_rows, "finishing_dhu"), 2),
            "otdf": round(avg_field(p_rows, "otdf"), 1)
        })

    # ---- Header ----
    header = {
        "company": "DEKKOISHO GROUP MANUFACTURING",
        "view": f"Consolidated View ({len(plants_data)} Units)",
        "month": f"{sorted_months[0]} – {latest_month} (YTD)"
    }

    data = {
        "header": header,
        "kpis": kpis,
        "efficiencyTrend": efficiency_trend,
        "gauges": gauges,
        "dhu": dhu,
        "minutesChart": minutes_chart,
        "units": units
    }

    return {"status": "success", "data": data}