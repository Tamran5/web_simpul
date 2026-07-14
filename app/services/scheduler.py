# import logging
# from datetime import date
# from apscheduler.schedulers.background import BackgroundScheduler

# from app.services.trend_service import fetch_external_trend_data
# from app.services.insight_service import generate_category_insights
# from app.models_visualization import ExternalTrendData

# logger = logging.getLogger(__name__)
# scheduler = BackgroundScheduler(timezone="Asia/Jakarta")


# def init_scheduler(app):

#     def scheduled_pipeline():
#         with app.app_context():
#             print("=== FETCH TREND ===")
#             fetch_external_trend_data()

#             print("=== GENERATE INSIGHT ===")
#             generate_category_insights()

#     # Hanya fetch jika data hari ini belum ada
#     with app.app_context():
#         today = date.today()

#         exists = (
#             ExternalTrendData.query
#             .filter(ExternalTrendData.period_date == today)
#             .first()
#         )

#         if exists:
#             print("Data trend hari ini sudah tersedia.")
#             print("=== GENERATE INSIGHT ===")
#             generate_category_insights()
#         else:
#             print("Data trend belum ada. Mengambil dari Google Trends...")
#             scheduled_pipeline()

#     scheduler.add_job(
#         scheduled_pipeline,
#         trigger="cron",
#         hour=2,
#         minute=0,
#         id="daily_trend_insight_job",
#         replace_existing=True
#     )

#     scheduler.start()
#     logger.info("Scheduler aktif.")