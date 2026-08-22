import os
import re
from collections import defaultdict
from flask import Flask, jsonify
from flask_cors import CORS
from pymongo import MongoClient

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from your frontend

# --- 1. MongoDB Connection (via environment variable) ---
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable not set!")

client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client["dgl_db"]
collection = db["monthly_records"]  # Make sure this matches your collection name


# --- 2. Helpers to parse numbers from strings like "20%" or "0.132" ---
def parse_num(v):
    """Convert any value (string, int, float) to a clean float."""
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
    """Parse a value, and optionally multiply by 100 for percentage display."""
    n = parse_num(v)
    return n * 100.0 if to_pct else n


def normalize_doc(doc):
    """
    Handle both flat column names and the nested "No" object for
    "No. of Brands/Buyers Handled" (from some older Excel versions).
    """
    # Try flat field first
    brands = doc.get("No. of Brands/Buyers Handled")
    # Fallback to nested "No" -> " of Brands/Buyers Handled"
    if brands is None and "No" in doc and isinstance(doc["No"], dict):
        brands = doc["No"].get(" of Brands/Buyers Handled", 0)
    if brands is None:
        brands = 0.0

    return {
        "month": doc.get("Month"),
        "plant": doc.get("Plant"),
        # All values are returned in the unit expected by the frontend:
        # - % values are multiplied by 100 (e.g., 98% -> 98.0)
        # - ratios (Cut-to-Ship) remain as decimals (e.g., 0.98)
        "efficiency": get_val(doc.get("Efficiency"), to_pct=True),
        "brands": get_val(brands, to_pct=True),          # e.g., 0.25 -> 25.0
        "style_change": get_val(doc.get("Style Change Over/Line"), to_pct=False),
        "cut_to_ship": get_val(doc.get("Cut-to-Ship Ratio"), to_pct=False),  # e.g., 98% -> 0.98
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


def mean(values):
    if not values:
        return 0.0
    return sum(values) / len(values)


def sum_values(values):
    return sum(values)


# --- 3. Main Endpoint ---
@app.route("/dashboard-data", methods=["GET"])
def dashboard_data():
    # Fetch all documents
    docs = list(collection.find())
    if not docs:
        return jsonify({"status": "error", "message": "No data found in collection"}), 404

    # Normalise each document
    rows = [normalize_doc(d) for d in docs]

    # ---- Group by Month ----
    months_data = defaultdict(list)
    for r in rows:
        months_data[r["month"]].append(r)

    # Sort months chronologically (assuming format "Jan-2026", etc.)
    # We'll rely on simple string sorting, but better: map month to index
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
    all_rows = rows  # full dataset

    # ---- Helper: average a field for a set of rows ----
    def avg_field(rows_list, field):
        return mean([r[field] for r in rows_list])

    def sum_field(rows_list, field):
        return sum([r[field] for r in rows_list])

    # ---- 3a. KPIs (latest vs previous) ----
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

    # ---- 3b. Efficiency Trend (monthly, YTD, target) ----
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
            "target": 65.0   # Fixed target (can be made dynamic later)
        })

    # ---- 3c. Gauges (overall YTD averages) ----
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

    # ---- 3d. DHU breakdown ----
    dhu = [
        {"label": "Sewing", "value": round(avg_field(all_rows, "sewing_dhu"), 2), "color": "#4A7BD9"},
        {"label": "Cutting", "value": round(avg_field(all_rows, "cutting_dhu"), 2), "color": "#F5B84D"},
        {"label": "Finishing", "value": round(avg_field(all_rows, "finishing_dhu"), 2), "color": "#8C7CF6"}
    ]

    # ---- 3e. Minutes Chart (millions) ----
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

    # ---- 3f. Units (plant breakdown) ----
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

    # ---- 3g. Header ----
    header = {
        "company": "DEKKOISHO GROUP MANUFACTURING",
        "view": f"Consolidated View ({len(plants_data)} Units)",
        "month": f"{sorted_months[0]} – {latest_month} (YTD)"
    }

    # ---- 4. Build final response ----
    data = {
        "header": header,
        "kpis": kpis,
        "efficiencyTrend": efficiency_trend,
        "gauges": gauges,
        "dhu": dhu,
        "minutesChart": minutes_chart,
        "units": units
    }

    return jsonify({"status": "success", "data": data})


# --- 5. Start the server ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)