import csv
import io
from datetime import date

from fastapi import FastAPI, HTTPException, UploadFile

from app.db import get_connection

app = FastAPI(title="FreshFlow Recommendations")

# Used both to validate uploads and to build the INSERT statements,
# so a file with unexpected columns is rejected instead of half-ingested
EXPECTED_COLUMNS = {
    "items": [
        "item_number", "name", "category", "is_bio",
        "purchase_price", "suggested_retail_price",
    ],
    "orderable_items": [
        "store_id", "item_number", "ordering_day", "delivery_day",
        "purchase_price", "suggested_retail_price", "profit_margin",
        "tags", "category",
    ],
    "inventory": ["store_id", "item_number", "day", "quantity"],
    "order_recommendations": [
        "store_id", "item_number", "ordering_day", "delivery_day",
        "recommended_quantity",
    ],
}


def parse_csv(upload: UploadFile, name: str) -> list[dict]:
    # utf-8-sig strips the BOM that Excel adds when exporting CSVs
    text = upload.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    expected = EXPECTED_COLUMNS[name]
    if reader.fieldnames != expected:
        raise HTTPException(
            status_code=400,
            detail=f"{name}: expected columns {expected}, got {reader.fieldnames}",
        )
    return list(reader)


@app.post("/load")
def load_data(
    items: UploadFile,
    orderable_items: UploadFile,
    inventory: UploadFile,
    order_recommendations: UploadFile,
):
    uploads = {
        "items": items,
        "orderable_items": orderable_items,
        "inventory": inventory,
        "order_recommendations": order_recommendations,
    }
    # Parse everything before touching the database, so one bad file
    # can't wipe data that was loaded earlier
    parsed = {name: parse_csv(upload, name) for name, upload in uploads.items()}

    conn = get_connection()
    counts = {}
    try:
        # single transaction: either every table is replaced or none are
        with conn:
            for name, rows in parsed.items():
                columns = EXPECTED_COLUMNS[name]
                placeholders = ", ".join("?" for _ in columns)
                values = [tuple(row[col] or None for col in columns) for row in rows]
                # delete + insert makes /load idempotent: re-uploading is safe
                conn.execute(f"DELETE FROM {name}")
                conn.executemany(f"INSERT INTO {name} VALUES ({placeholders})", values)
                counts[name] = len(values)
    finally:
        conn.close()

    return {"rows_loaded": counts}


@app.get("/stores/{store_id}/recommendations")
def get_recommendations(store_id: str, day: str):
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be in YYYY-MM-DD format")

    conn = get_connection()
    try:
        # distinguish "nothing loaded yet" (404) from "no recommendations
        # for this store/day" (200 with an empty list)
        loaded = conn.execute("SELECT COUNT(*) FROM order_recommendations").fetchone()[0]
        if loaded == 0:
            raise HTTPException(
                status_code=404,
                detail="No data loaded yet. POST the CSV files to /load first.",
            )

        # LEFT JOIN because some recommendations reference items that are
        # missing from the catalog - serve those with null name/category
        # rather than dropping them
        rows = conn.execute(
            """
            SELECT r.item_number, i.name, i.category, r.delivery_day,
                   r.recommended_quantity
            FROM order_recommendations r
            LEFT JOIN items i ON i.item_number = r.item_number
            WHERE r.store_id = ? AND r.ordering_day = ?
            ORDER BY r.item_number
            """,
            (store_id, day),
        ).fetchall()
    finally:
        conn.close()

    return {
        "store_id": store_id,
        "day": day,
        "recommendations": [dict(row) for row in rows],
    }
