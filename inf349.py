import urllib.request
import urllib.error
import json
from flask import Flask, jsonify, request
from peewee import SqliteDatabase, Model, CharField, FloatField, BooleanField, IntegerField
import click
from flask.cli import with_appcontext

app = Flask(__name__)
db = SqliteDatabase('shops.db')

class BaseModel(Model):
    class Meta: 
        database = db

class Product(BaseModel):
    id = IntegerField(primary_key=True)
    name = CharField()
    description = CharField()
    price = FloatField()
    in_stock = BooleanField()
    image = CharField()
    weight = IntegerField(null=True)

class Order(BaseModel):
    id = IntegerField(primary_key=True)
    product_id = IntegerField()
    quantity = IntegerField()
    total_price = FloatField()
    shipping_price = FloatField()
    email = CharField(null=True)
    country = CharField(null=True)
    address = CharField(null=True)
    postal_code = CharField(null=True)
    city = CharField(null=True)
    province = CharField(null=True)
    paid = BooleanField(default=False)
    transaction_id = CharField(null=True)
    transaction_success = BooleanField(null=True)
    transaction_amount = FloatField(null=True)
    cc_name = CharField(null=True)
    cc_first_digits = CharField(null=True)
    cc_last_digits = CharField(null=True)
    cc_expiration_year = IntegerField(null=True)
    cc_expiration_month = IntegerField(null=True)

@click.command('init-db')
@with_appcontext
def init_db():
    db.connect()
    db.create_tables([Product, Order])
    db.close()

app.cli.add_command(init_db)

def fetch_products():
    try:
        if Product.table_exists() and Product.select().count() == 0:
            req = urllib.request.urlopen("https://dimensweb.uqac.ca/~jgnault/shops/products/")
            data = json.loads(req.read())
            for p in data['products']:
                Product.create(
                    id=p['id'], name=p['name'], description=p['description'], 
                    price=p['price'], in_stock=p['in_stock'], image=p['image'], weight=p.get('weight')
                )
    except:
        pass

fetch_products()

def get_tax(province):
    return {"QC": 0.15, "ON": 0.13, "AB": 0.05, "BC": 0.12, "NS": 0.14}.get(province, 0)

def format_order(order, product):
    tax_rate = get_tax(order.province)
    taxed_price = order.total_price + (order.total_price * tax_rate)

    ship_info = {}
    if order.country:
        ship_info = {"country": order.country, "address": order.address, "postal_code": order.postal_code, "city": order.city, "province": order.province}

    cc_info = {}
    if order.cc_name:
        cc_info = {"name": order.cc_name, "first_digits": order.cc_first_digits, "last_digits": order.cc_last_digits, "expiration_year": order.cc_expiration_year, "expiration_month": order.cc_expiration_month}

    txn_info = {}
    if order.transaction_id:
        txn_info = {"id": order.transaction_id, "success": order.transaction_success, "amount_charged": order.transaction_amount}

    return jsonify({
        "order": {
            "id": order.id, "total_price": order.total_price, "total_price_tax": taxed_price,
            "email": order.email, "credit_card": cc_info, "shipping_information": ship_info,
            "paid": order.paid, "transaction": txn_info,
            "product": {"id": product.id, "quantity": order.quantity},
            "shipping_price": order.shipping_price
        }
    })

@app.route('/', methods=['GET'])
def get_all_products():
    prods = [{"id": p.id, "name": p.name, "description": p.description, "price": p.price, "in_stock": p.in_stock, "image": p.image, "weight": p.weight} for p in Product.select()]
    return jsonify({"products": prods})

@app.route('/order', methods=['POST'])
def create_order():
    data = request.get_json()
    if not data or 'product' not in data or 'id' not in data['product'] or 'quantity' not in data['product'] or data['product']['quantity'] < 1:
        return jsonify({"errors": {"product": {"code": "missing-fields", "name": "La création d'une commande nécessite un produit"}}}), 422

    try:
        product = Product.get(Product.id == data['product']['id'])
    except Product.DoesNotExist:
        return jsonify({"error": "Product not found"}), 404

    if not product.in_stock:
        return jsonify({"errors": {"product": {"code": "out-of-inventory", "name": "Le produit demandé n'est pas en inventaire"}}}), 422

    qty = data['product']['quantity']
    price = product.price * qty
    weight = (product.weight or 0) * qty

    shipping = 500
    if weight > 2000:
        shipping = 2500
    elif weight > 500:
        shipping = 1000

    order = Order.create(product_id=product.id, quantity=qty, total_price=price, shipping_price=shipping)
    return "", 302, {"Location": f"/order/{order.id}"}

@app.route('/order/<int:order_id>', methods=['GET'])
def get_order_endpoint(order_id):
    try:
        order = Order.get(Order.id == order_id)
        product = Product.get(Product.id == order.product_id)
        return format_order(order, product)
    except:
        return jsonify({"error": "Not found"}), 404

@app.route('/order/<int:order_id>', methods=['PUT'])
def update_order(order_id):
    try:
        order = Order.get(Order.id == order_id)
        product = Product.get(Product.id == order.product_id)
    except:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json()
    
    if 'order' in data and 'shipping_information' in data['order']:
        info = data['order']
        ship = info.get('shipping_information', {})
        if 'email' not in info or not all(k in ship for k in ('country', 'address', 'postal_code', 'city', 'province')):
            return jsonify({"errors": {"order": {"code": "missing-fields", "name": "Il manque un ou plusieurs champs obligatoires"}}}), 422
        
        order.email = info['email']
        order.country = ship['country']
        order.address = ship['address']
        order.postal_code = ship['postal_code']
        order.city = ship['city']
        order.province = ship['province']
        order.save()
        return format_order(order, product)

    if 'credit_card' in data:
        if order.paid:
            return jsonify({"errors": {"order": {"code": "already-paid", "name": "La commande a déjà été payée."}}}), 422
        if not order.email:
            return jsonify({"errors": {"order": {"code": "missing-fields", "name": "Les informations du client sont nécessaires."}}}), 422

        tax_rate = get_tax(order.province)
        amt = int(order.total_price + (order.total_price * tax_rate) + order.shipping_price)

        try:
            req = urllib.request.Request("https://dimensweb.uqac.ca/~jgnault/shops/pay/", data=json.dumps({"credit_card": data['credit_card'], "amount_charged": amt}).encode(), headers={'Content-Type': 'application/json'})
            res = urllib.request.urlopen(req)
            res_data = json.loads(res.read())
        except urllib.error.HTTPError as e:
            return jsonify(json.loads(e.read())), 422

        order.paid = True
        order.transaction_id = res_data['transaction']['id']
        order.transaction_success = res_data['transaction']['success']
        order.transaction_amount = res_data['transaction']['amount_charged']
        order.cc_name = res_data['credit_card']['name']
        order.cc_first_digits = res_data['credit_card']['first_digits']
        order.cc_last_digits = res_data['credit_card']['last_digits']
        order.cc_expiration_year = res_data['credit_card']['expiration_year']
        order.cc_expiration_month = res_data['credit_card']['expiration_month']
        order.save()
        return format_order(order, product)

    return jsonify({"errors": {"order": {"code": "missing-fields", "name": "Requête invalide"}}}), 422