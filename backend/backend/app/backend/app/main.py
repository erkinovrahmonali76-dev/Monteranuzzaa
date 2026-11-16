import os, hmac, hashlib, json, time, asyncio, html
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Update, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from fastapi import FastAPI, Depends, Header, HTTPException, Request, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .models import Base, User, Product, Favorite, Order, Promo, Setting

E = os.environ
BOT_TOKEN = E["BOT_TOKEN"]
ADMINS = {int(x) for x in E.get("ADMIN_ID", "").split(",") if x.strip()}
URL = (E.get("TELEGRAM_WEBAPP_URL") or E.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
SECRET = E.get("SECRET_KEY", "change-me")
DBURL = E["DATABASE_URL"].split("?")[0].replace("postgres://", "postgresql://").replace("postgresql://", "postgresql+asyncpg://")
CATS = ["T-shirt", "Polo", "Sviter", "Hoodie", "Sweatshirt", "Ko‘ylak", "Shim", "Jinsi", "Komplekt", "Kurtka", "Palto", "Aksessuar"]
ST = {"new": "🟡 Buyurtmangiz qabul qilindi", "confirmed": "🔵 Buyurtmangiz tasdiqlandi", "preparing": "🟠 Buyurtmangiz tayyorlanmoqda",
      "shipping": "🚚 Buyurtmangiz kuryerga berildi", "delivered": "🟢 Buyurtmangiz yetkazildi", "cancelled": "🔴 Buyurtmangiz bekor qilindi"}

engine = create_async_engine(DBURL, connect_args={"ssl": True}, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

def kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛍 Do‘konni ochish", web_app=WebAppInfo(url=URL))]])

@dp.message(CommandStart())
async def start(m: Message):
    async with Session() as s:
        u = await s.get(User, m.from_user.id) or User(id=m.from_user.id)
        u.username, u.first_name, u.last_name = m.from_user.username, m.from_user.first_name, m.from_user.last_name
        s.add(u); await s.commit()
    await m.answer("MONTERA.UZ ga xush kelibsiz 👋", reply_markup=kb())

@dp.message(F.photo)
async def photo(m: Message):  # admin rasm yuboradi -> mahsulot uchun kod oladi
    if m.from_user.id in ADMINS:
        await m.reply(f"<code>tg:{m.photo[-1].file_id}</code>\nShu kodni mahsulot rasmiga qo‘ying.")

@asynccontextmanager
async def lifespan(_):
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    if URL: await bot.set_webhook(f"{URL}/webhook/{SECRET}", drop_pending_updates=True)
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

async def db():
    async with Session() as s: yield s

async def auth(x_init_data: str = Header(""), s: AsyncSession = Depends(db)) -> User:
    d = dict(parse_qsl(x_init_data)); h = d.pop("hash", "")
    key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    ok = h and hmac.compare_digest(hmac.new(key, chk.encode(), hashlib.sha256).hexdigest(), h)
    if not ok or time.time() - int(d.get("auth_date", 0)) > 86400:
        raise HTTPException(401, "Iltimos, do‘konni Telegram bot orqali oching")
    t = json.loads(d["user"])
    u = await s.get(User, t["id"]) or User(id=t["id"])
    u.username, u.first_name, u.last_name = t.get("username"), t.get("first_name"), t.get("last_name")
    if u.blocked: raise HTTPException(403, "Siz bloklangansiz")
    s.add(u); await s.commit()
    return u

def admin(u: User = Depends(auth)):
    if u.id not in ADMINS: raise HTTPException(403, "Ruxsat yo‘q")
    return u

def d(o):
    return {c.name: (v.isoformat() if isinstance(v := getattr(o, c.name), datetime) else v) for c in o.__table__.columns}

async def say(uid, text):
    try: await bot.send_message(uid, text)
    except Exception: pass

async def fees(s):
    r = await s.get(Setting, "delivery")
    return r.value if r else {"tashkent": 30000, "region": 50000}

def promo_off(pr, sub):
    if not pr or not pr.active or (pr.expires and pr.expires < datetime.utcnow()) or (pr.limit and pr.used >= pr.limit): return None
    return min(sub, sub * (pr.percent or 0) // 100 + (pr.fixed or 0))

@app.get("/health")
async def health(): return {"ok": True}

@app.post("/webhook/{secret}")
async def webhook(secret: str, req: Request):
    if secret != SECRET: raise HTTPException(404)
    await dp.feed_update(bot, Update.model_validate(await req.json(), context={"bot": bot}))
    return {"ok": True}

@app.get("/img/{fid}")
async def img(fid: str):
    try: f = await bot.get_file(fid)
    except Exception: raise HTTPException(404)
    async with aiohttp.ClientSession() as c, c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}") as r:
        data = await r.read()
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public,max-age=31536000"})

# ---------- Mijoz API ----------
@app.get("/api/me")
async def me(u: User = Depends(auth)): return {"id": u.id, "first_name": u.first_name, "is_admin": u.id in ADMINS}

@app.get("/api/config")
async def config(_=Depends(auth), s=Depends(db)): return {**await fees(s), "categories": CATS}

@app.get("/api/products")
async def products(_=Depends(auth), s=Depends(db)):
    return [d(p) for p in (await s.scalars(select(Product).where(Product.active == True).order_by(Product.id.desc()))).all()]

@app.get("/api/favorites")
async def favs(u=Depends(auth), s=Depends(db)):
    return (await s.scalars(select(Favorite.product_id).where(Favorite.user_id == u.id))).all()

@app.post("/api/favorites/{pid}")
async def fav(pid: int, u=Depends(auth), s=Depends(db)):
    f = await s.get(Favorite, (u.id, pid))
    if f: await s.delete(f)
    else: s.add(Favorite(user_id=u.id, product_id=pid))
    await s.commit(); return {"fav": not f}

class PromoIn(BaseModel):
    code: str; subtotal: int

@app.post("/api/promo/check")
async def promo_check(b: PromoIn, _=Depends(auth), s=Depends(db)):
    off = promo_off(await s.get(Promo, b.code.strip().upper()), b.subtotal)
    if off is None: raise HTTPException(400, "Promo kod yaroqsiz yoki muddati tugagan")
    return {"code": b.code.strip().upper(), "discount": off}

class Item(BaseModel):
    id: int; color: str; size: str; qty: int = Field(ge=1, le=20)

class OrderIn(BaseModel):
    name: str = Field(min_length=2, max_length=80); phone: str = Field(min_length=7, max_length=20)
    region: str = Field(max_length=60); city: str = Field(min_length=2, max_length=80)
    address: str = Field(min_length=3, max_length=300); note: str = Field("", max_length=300)
    delivery: str = "courier"; promo: str = ""
    items: list[Item] = Field(min_length=1, max_length=30)

@app.post("/api/orders")
async def make_order(b: OrderIn, bg: BackgroundTasks, u=Depends(auth), s=Depends(db)):
    ps = {p.id: p for p in (await s.scalars(select(Product).where(Product.id.in_([i.id for i in b.items])).with_for_update())).all()}
    lines, sub = [], 0
    for i in b.items:
        p, k = ps.get(i.id), f"{i.color}|{i.size}"
        if not p or not p.active: raise HTTPException(400, "Mahsulot topilmadi")
        have = (p.stock or {}).get(k, 0)
        if have < i.qty: raise HTTPException(400, f"{p.name} ({i.color}, {i.size}): omborda {have} dona qoldi")
        p.stock = {**p.stock, k: have - i.qty}; p.sold = (p.sold or 0) + i.qty
        lines.append({"id": p.id, "name": p.name, "color": i.color, "size": i.size, "qty": i.qty, "price": p.price})
        sub += p.price * i.qty
    code = b.promo.strip().upper(); pr = await s.get(Promo, code) if code else None
    off = 0
    if code:
        off = promo_off(pr, sub)
        if off is None: raise HTTPException(400, "Promo kod yaroqsiz")
        pr.used = (pr.used or 0) + 1
    f = await fees(s); fee = f["tashkent"] if b.region == "Toshkent shahri" else f["region"]
    o = Order(user_id=u.id, name=b.name, phone=b.phone, region=b.region, city=b.city, address=b.address, note=b.note,
              delivery="post" if b.delivery == "post" else "courier", items=lines, subtotal=sub, discount=off, fee=fee,
              total=sub - off + fee, promo=code)
    s.add(o); await s.flush(); o.number = f"MON-{10000 + o.id}"; await s.commit()
    bg.add_task(say, u.id, f"{ST['new']} ✅\nBuyurtma: <b>#{o.number}</b>\nJami: {o.total:,} so‘m".replace(",", " "))
    txt = (f"🆕 <b>#{o.number}</b>\n{html.escape(o.name)} · {html.escape(o.phone)}\n{html.escape(o.region)}, {html.escape(o.city)}, {html.escape(o.address)}\n"
           + "\n".join(f"• {html.escape(l['name'])} {html.escape(l['color'])}/{html.escape(l['size'])} ×{l['qty']}" for l in lines) + f"\nJami: {o.total:,} so‘m".replace(",", " "))
    for a in ADMINS: bg.add_task(say, a, txt)
    return d(o)

@app.get("/api/orders")
async def my_orders(u=Depends(auth), s=Depends(db)):
    return [d(o) for o in (await s.scalars(select(Order).where(Order.user_id == u.id).order_by(Order.id.desc()).limit(50))).all()]

# ---------- Admin API ----------
class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=160); description: str = ""; category: str
    price: int = Field(ge=0); old_price: Optional[int] = None
    images: list[str] = []; colors: list[str] = []; sizes: list[str] = []; stock: dict[str, int] = {}
    material: str = ""; sku: str = ""; active: bool = True

@app.get("/api/admin/stats")
async def stats(_=Depends(admin), s=Depends(db)):
    t0 = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0); ok = Order.status != "cancelled"
    n = lambda *w: s.scalar(select(func.count()).select_from(Order).where(*w))
    rev = lambda *w: s.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(ok, *w))
    top = (await s.execute(select(Product.name, Product.sold).order_by(Product.sold.desc()).limit(5))).all()
    return {"users": await s.scalar(select(func.count()).select_from(User)),
            "new_users": await s.scalar(select(func.count()).select_from(User).where(User.created_at >= t0)),
            "orders": await n(), "orders_today": await n(Order.created_at >= t0),
            "revenue": await rev(), "revenue_today": await rev(Order.created_at >= t0),
            "top": [{"name": a, "sold": b} for a, b in top]}

@app.get("/api/admin/orders")
async def a_orders(_=Depends(admin), s=Depends(db)):
    return [d(o) for o in (await s.scalars(select(Order).order_by(Order.id.desc()).limit(100))).all()]

class StatusIn(BaseModel):
    status: str

@app.post("/api/admin/orders/{oid}/status")
async def a_status(oid: int, b: StatusIn, _=Depends(admin), s=Depends(db)):
    o = await s.get(Order, oid)
    if not o or b.status not in ST: raise HTTPException(400, "Noto‘g‘ri so‘rov")
    if b.status == "cancelled" and o.status != "cancelled":  # ombor qaytariladi
        for l in o.items:
            p = await s.get(Product, l["id"])
            if p: k = f"{l['color']}|{l['size']}"; p.stock = {**p.stock, k: p.stock.get(k, 0) + l["qty"]}
    o.status = b.status; await s.commit()
    await say(o.user_id, f"{ST[b.status]}\n<b>#{o.number}</b>"); return d(o)

@app.get("/api/admin/products")
async def a_products(_=Depends(admin), s=Depends(db)):
    return [d(p) for p in (await s.scalars(select(Product).order_by(Product.id.desc()))).all()]

@app.post("/api/admin/products")
async def a_add(b: ProductIn, _=Depends(admin), s=Depends(db)):
    p = Product(**b.model_dump()); s.add(p); await s.commit(); return d(p)

@app.put("/api/admin/products/{pid}")
async def a_edit(pid: int, b: ProductIn, _=Depends(admin), s=Depends(db)):
    p = await s.get(Product, pid)
    if not p: raise HTTPException(404, "Topilmadi")
    for k, v in b.model_dump().items(): setattr(p, k, v)
    await s.commit(); return d(p)

@app.delete("/api/admin/products/{pid}")
async def a_del(pid: int, _=Depends(admin), s=Depends(db)):
    p = await s.get(Product, pid)
    if p: await s.delete(p); await s.commit()
    return {"ok": True}

class PromoNew(BaseModel):
    code: str; percent: int = 0; fixed: int = 0; expires: Optional[datetime] = None; limit: Optional[int] = None

@app.get("/api/admin/promos")
async def a_promos(_=Depends(admin), s=Depends(db)):
    return [d(p) for p in (await s.scalars(select(Promo))).all()]

@app.post("/api/admin/promos")
async def a_promo(b: PromoNew, _=Depends(admin), s=Depends(db)):
    await s.merge(Promo(**{**b.model_dump(), "code": b.code.strip().upper(), "active": True})); await s.commit(); return {"ok": True}

class FeeIn(BaseModel):
    tashkent: int = Field(ge=0); region: int = Field(ge=0)

@app.put("/api/admin/delivery")
async def a_fee(b: FeeIn, _=Depends(admin), s=Depends(db)):
    await s.merge(Setting(key="delivery", value=b.model_dump())); await s.commit(); return b

class BlockIn(BaseModel):
    blocked: bool

@app.get("/api/admin/users")
async def a_users(q: str = "", _=Depends(admin), s=Depends(db)):
    st = select(User).order_by(User.created_at.desc()).limit(50)
    if q: st = select(User).where((User.username.ilike(f"%{q}%")) | (User.id == int(q) if q.isdigit() else False)).limit(50)
    return [d(u) for u in (await s.scalars(st)).all()]

@app.post("/api/admin/users/{uid}/block")
async def a_block(uid: int, b: BlockIn, _=Depends(admin), s=Depends(db)):
    u = await s.get(User, uid)
    if u: u.blocked = b.blocked; await s.commit()
    return {"ok": True}

class BcIn(BaseModel):
    text: str = Field(min_length=1, max_length=3500)

async def bcast(text):
    async with Session() as s: ids = (await s.scalars(select(User.id).where(User.blocked == False))).all()
    for i in ids:
        try: await bot.send_message(i, text, parse_mode=None)
        except Exception: pass
        await asyncio.sleep(0.05)

@app.post("/api/admin/broadcast")
async def a_bc(b: BcIn, bg: BackgroundTasks, _=Depends(admin)):
    bg.add_task(bcast, b.text); return {"ok": True}

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))
