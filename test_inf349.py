import pytest
from inf349 import app, db, Product, Order

@pytest.fixture
def client():
    app.config['TESTING'] = True
    db.init(':memory:')
    db.connect()
    db.create_tables([Product, Order])
    
    Product.create(id=1, name="Test Item", description="Test", price=10.0, in_stock=True, image="test.jpg", weight=100)
    
    with app.test_client() as c:
        yield c
        
    db.drop_tables([Product, Order])
    db.close()

def test_get_products(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b"Test Item" in response.data

def test_create_order_missing_data(client):
    response = client.post('/order', json={})
    assert response.status_code == 422

def test_create_order_success(client):
    response = client.post('/order', json={"product": {"id": 1, "quantity": 2}})
    assert response.status_code == 302