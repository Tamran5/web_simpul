from flask import Blueprint, jsonify
from app.services.trend_service import fetch_external_trend_data
from app.services.insight_service import generate_category_insights

scheduler_bp = Blueprint("scheduler", __name__)

@scheduler_bp.route("/api/scheduler/run", methods=["GET"])
def run_scheduler():

    fetch_external_trend_data()
    generate_category_insights()

    return jsonify({
        "status": "success",
        "message": "Trend dan insight berhasil diperbarui."
    })