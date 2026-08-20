import os
import pymongo
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ------------------------------------------------
# FIX: Add CORS Middleware with type ignore comments
# to silence PyCharm's false-positive warnings.
# ------------------------------------------------
app.add_middleware(  # type: ignore
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.getenv("MONGO_URI")


def get_db():
    if not MONGO_URI:
        print("ERROR: MONGO_URI is not set in environment variables.")
        return None
    try:
        # ------------------------------------------------
        # FIX: Force TLS with relaxed certificate validation
        # to fix the SSL handshake error on Render free tier.
        # ------------------------------------------------
        client = pymongo.MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000,
            tls=True,
            tlsAllowInvalidCertificates=True
        )
        # Quick connection test
        client.admin.command('ping')
        print("MongoDB connection successful!")
        return client["dgl_db"]
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


@app.get("/")
async def health_check():
    return {"message": "DGL Dashboard API is running"}


@app.get("/dashboard-data")
async def get_dashboard_data():
    db = get_db()
    if db is None:
        return {"error": "Database connection failed. Check logs."}

    collection = db["monthly_records"]

    # Safe aggregation pipeline with type-casting
    pipeline = [
        {
            "$addFields": {
                "Total_Orders": {"$ifNull": [{"$toDouble": "$Total_Orders"}, 0]},
                "Total_Production": {"$ifNull": [{"$toDouble": "$Total_Production"}, 0]},
            }
        },
        {
            "$group": {
                "_id": "$Month",
                "total_orders": {"$sum": "$Total_Orders"},
                "total_production": {"$sum": "$Total_Production"},
            }
        },
        {
            "$sort": {"_id": 1}
        }
    ]

    results = list(collection.aggregate(pipeline))

    clean_results = []
    for item in results:
        clean_results.append({
            "month": item["_id"],
            "total_orders": item["total_orders"],
            "total_production": item["total_production"]
        })

    return {"status": "success", "data": clean_results}