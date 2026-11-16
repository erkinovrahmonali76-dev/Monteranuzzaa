from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, JSON, DateTime, Text
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase): pass
now = datetime.utcnow

class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    username = Column(String(64)); first_name = Column(String(100)); last_name = Column(String(100))
    blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(160)); description = Column(Text, default="")
    category = Column(String(40), index=True)
    price = Column(Integer); old_price = Column(Integer)
    images = Column(JSON, default=list); colors = Column(JSON, default=list); sizes = Column(JSON, default=list)
    stock = Column(JSON, default=dict)  # {"Black|M": 5}
    material = Column(String(80), default=""); sku = Column(String(40), default="")
    sold = Column(Integer, default=0); active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=now)

class Favorite(Base):
    __tablename__ = "favorites"
    user_id = Column(BigInteger, primary_key=True); product_id = Column(Integer, primary_key=True)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    number = Column(String(20), index=True)
    user_id = Column(BigInteger, index=True)
    name = Column(String(80)); phone = Column(String(20)); region = Column(String(60)); city = Column(String(80))
    address = Column(String(300)); note = Column(String(300), default=""); delivery = Column(String(10))
    items = Column(JSON); subtotal = Column(Integer); discount = Column(Integer, default=0)
    fee = Column(Integer); total = Column(Integer); promo = Column(String(30), default="")
    status = Column(String(12), default="new", index=True)
    created_at = Column(DateTime, default=now)

class Promo(Base):
    __tablename__ = "promo_codes"
    code = Column(String(30), primary_key=True)
    percent = Column(Integer, default=0); fixed = Column(Integer, default=0)
    expires = Column(DateTime); limit = Column(Integer); used = Column(Integer, default=0)
    active = Column(Boolean, default=True)

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(40), primary_key=True); value = Column(JSON)
