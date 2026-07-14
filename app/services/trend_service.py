import logging
from pytrends.request import TrendReq
import pandas as pd
from app.extensions import db
import traceback
from app.models_visualization import ExternalTrendData

logger = logging.getLogger(__name__)

# PENTING: sesuaikan value di kanan (kategori) PERSIS dengan isi kolom Vendor.category di Supabase.
# Cek dulu dengan: db.session.query(Vendor.category).distinct().all()
KEYWORD_CATEGORY_MAP = {
    "gedung pernikahan":   "Gedung",
    "catering pernikahan": "Catering",
    "dekorasi pernikahan": "Dekorasi",
    "wedding organizer":   "WO",
}
REGION = "ID"


def fetch_external_trend_data():
    try:
        pytrends = TrendReq(hl='id-ID', tz=420)
        keywords = list(KEYWORD_CATEGORY_MAP.keys())
        pytrends.build_payload(keywords, timeframe='today 12-m', geo=REGION)
        df = pytrends.interest_over_time()

        print(df.head())
        print(df.shape)

        if df.empty:
            logger.warning("Data trend eksternal kosong, skip penyimpanan.")
            return

        df = df.drop(columns=['isPartial'], errors='ignore')
        df_long = df.reset_index().melt(id_vars='date', var_name='keyword', value_name='score')
        df_long['score'] = pd.to_numeric(df_long['score'], errors='coerce').fillna(0).astype(int)

        for kw in keywords:
            ExternalTrendData.query.filter_by(keyword=kw, region=REGION).delete()

        rows = [
            ExternalTrendData(
                keyword=row['keyword'], region=REGION,
                period_date=row['date'].date(), interest_score=int(row['score'])
            )
            for _, row in df_long.iterrows()
        ]
        db.session.bulk_save_objects(rows)
        db.session.commit()
        logger.info(f"Berhasil menyimpan {len(rows)} baris data trend eksternal.")
        print(ExternalTrendData.query.count())

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        logger.error(e)