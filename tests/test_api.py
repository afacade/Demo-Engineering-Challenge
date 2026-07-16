import pytest
from fastapi.testclient import TestClient

from app.main import app

ITEMS_CSV = (
    "item_number,name,category,is_bio,purchase_price,suggested_retail_price\n"
    "1001,Organic Bananas,Fruits,False,0.89,1.49\n"
)
ORDERABLE_CSV = (
    "store_id,item_number,ordering_day,delivery_day,purchase_price,"
    "suggested_retail_price,profit_margin,tags,category\n"
    "store_a,1001,2024-01-01,2024-01-02,0.89,1.49,0.4,,Fruits\n"
    # trailing comma, like some rows in the real orderable_items.csv
    "store_a,1001,2024-01-02,2024-01-03,0.89,1.49,0.4,,Fruits,\n"
)
INVENTORY_CSV = (
    "store_id,item_number,day,quantity\n"
    "store_a,1001,2024-01-01,16.4\n"
)
# the real file has float item numbers, messy store ids, exact duplicates
# and negative quantities - one row of each here
RECS_CSV = (
    "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
    "store_a,1001,2024-01-01,2024-01-02,18\n"
    "store_a,9999,2024-01-01,2024-01-02,5\n"
    "store_a,1001.0,2024-01-05,2024-01-06,7\n"
    " STORE_A,1001,2024-01-08,2024-01-09,4\n"
    "store_a,1001,2024-01-09,2024-01-10,-3\n"
    "store_a,1001,2024-01-09,2024-01-10,-3\n"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    return TestClient(app)


def load_files(client, items_csv=ITEMS_CSV):
    return client.post(
        "/load",
        files={
            "items": ("items.csv", items_csv, "text/csv"),
            "orderable_items": ("orderable_items.csv", ORDERABLE_CSV, "text/csv"),
            "inventory": ("inventory.csv", INVENTORY_CSV, "text/csv"),
            "order_recommendations": ("order_recommendations.csv", RECS_CSV, "text/csv"),
        },
    )


def test_load_drops_exact_duplicates(client):
    response = load_files(client)
    assert response.status_code == 200
    assert response.json()["rows_loaded"]["order_recommendations"] == 5


def test_trailing_comma_rows_are_loaded(client):
    response = load_files(client)
    assert response.json()["rows_loaded"]["orderable_items"] == 2


def test_float_item_numbers_are_normalized(client):
    load_files(client)
    response = client.get("/stores/store_a/recommendations", params={"day": "2024-01-05"})
    rec = response.json()["recommendations"][0]
    assert rec["item_number"] == 1001
    assert rec["name"] == "Organic Bananas"


def test_messy_store_ids_are_normalized(client):
    load_files(client)
    response = client.get("/stores/STORE_A/recommendations", params={"day": "2024-01-08"})
    assert len(response.json()["recommendations"]) == 1


def test_negative_quantity_served_as_zero(client):
    load_files(client)
    response = client.get("/stores/store_a/recommendations", params={"day": "2024-01-09"})
    recs = response.json()["recommendations"]
    assert len(recs) == 1
    assert recs[0]["recommended_quantity"] == 0


def test_recommendations_include_item_details(client):
    load_files(client)
    response = client.get("/stores/store_a/recommendations", params={"day": "2024-01-01"})
    assert response.status_code == 200
    first = response.json()["recommendations"][0]
    assert first == {
        "item_number": 1001,
        "name": "Organic Bananas",
        "category": "Fruits",
        "delivery_day": "2024-01-02",
        "recommended_quantity": 18,
    }


def test_item_missing_from_catalog_has_null_name(client):
    load_files(client)
    response = client.get("/stores/store_a/recommendations", params={"day": "2024-01-01"})
    second = response.json()["recommendations"][1]
    assert second["item_number"] == 9999
    assert second["name"] is None


def test_reload_replaces_data(client):
    load_files(client)
    load_files(client)
    response = client.get("/stores/store_a/recommendations", params={"day": "2024-01-01"})
    assert len(response.json()["recommendations"]) == 2


def test_unknown_day_returns_empty_list(client):
    load_files(client)
    response = client.get("/stores/store_a/recommendations", params={"day": "2030-01-01"})
    assert response.status_code == 200
    assert response.json()["recommendations"] == []


def test_before_load_returns_404(client):
    response = client.get("/stores/store_a/recommendations", params={"day": "2024-01-01"})
    assert response.status_code == 404


def test_wrong_columns_rejected(client):
    response = load_files(client, items_csv="wrong,headers\n1,2\n")
    assert response.status_code == 400


def test_failed_load_keeps_previous_data(client):
    load_files(client)

    # two different rows with the same primary key make the insert blow up
    # mid-transaction, after the delete already ran
    bad_items = (
        "item_number,name,category,is_bio,purchase_price,suggested_retail_price\n"
        "1001,Organic Bananas,Fruits,False,0.89,1.49\n"
        "1001,Not The Same Bananas,Fruits,False,0.89,1.49\n"
    )
    response = load_files(client, items_csv=bad_items)
    assert response.status_code == 500
    assert "unchanged" in response.json()["detail"]

    # the rollback means the first load is still fully there
    response = client.get("/stores/store_a/recommendations", params={"day": "2024-01-01"})
    assert len(response.json()["recommendations"]) == 2
    assert response.json()["recommendations"][0]["name"] == "Organic Bananas"


def test_invalid_day_format_rejected(client):
    load_files(client)
    response = client.get("/stores/store_a/recommendations", params={"day": "not-a-date"})
    assert response.status_code == 400
