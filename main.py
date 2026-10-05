import os, secrets, hashlib, uuid, sqlite3
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

SEC = ("men", "women", "kids")
PAY = ("cash", "easypaisa", "jazzcash", "nayapay")
STATUS = ("pending", "dispatched", "delivered")
TOK = set()
SQLITE_FILE = "alhareem.db"

# Detect DB Backend
DB_TYPE = "sqlite"
try:
    import mysql.connector
    _c = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "1234"),
        database=os.getenv("DB_NAME", "alhareem")
    )
    _c.close()
    DB_TYPE = "mysql"
except Exception:
    DB_TYPE = "sqlite"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


def now():  # Pakistan time (UTC+5)
    return datetime.utcnow() + timedelta(hours=5)


def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_FILE)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cloths (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      section TEXT NOT NULL,
      name TEXT NOT NULL,
      color TEXT DEFAULT '',
      size TEXT DEFAULT '',
      price INTEGER NOT NULL,
      discount_type TEXT DEFAULT 'none',
      discount_value INTEGER DEFAULT 0,
      stock INTEGER DEFAULT 0,
      image TEXT,
      created_at TEXT NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      phone TEXT NOT NULL,
      city TEXT DEFAULT '',
      address TEXT DEFAULT ''
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      cloth_id INTEGER NOT NULL,
      customer_id INTEGER NOT NULL,
      qty INTEGER NOT NULL,
      unit_price INTEGER NOT NULL,
      total INTEGER NOT NULL,
      pay_method TEXT NOT NULL,
      tid TEXT DEFAULT '',
      status TEXT DEFAULT 'pending',
      created_at TEXT NOT NULL,
      FOREIGN KEY (cloth_id) REFERENCES cloths(id),
      FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    """)
    conn.commit()
    conn.close()


def q(sql, args=(), one=False, write=False):
    if DB_TYPE == "mysql":
        import mysql.connector
        c = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", "1234"),
            database=os.getenv("DB_NAME", "alhareem")
        )
        cur = c.cursor(dictionary=True)
        try:
            cur.execute(sql, args)
            if write:
                c.commit()
                return cur.lastrowid
            return cur.fetchone() if one else cur.fetchall()
        except mysql.connector.Error as e:
            raise HTTPException(400, "Database error: " + str(e.msg))
        finally:
            cur.close()
            c.close()
    else:
        conn = sqlite3.connect(SQLITE_FILE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        sqlite_sql = sql.replace("%s", "?")
        try:
            cur.execute(sqlite_sql, tuple(args))
            if write:
                conn.commit()
                return cur.lastrowid
            rows = cur.fetchall()
            if one:
                return dict(rows[0]) if rows else None
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise HTTPException(400, "Database error: " + str(e))
        finally:
            cur.close()
            conn.close()


def hp(p, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), salt.encode(), 100000).hex()


def auth(x_token: str = Header("")):
    if x_token not in TOK:
        raise HTTPException(401, "Please log in")


def final_price(c):
    if c["discount_type"] == "percent":
        return max(0, round(c["price"] * (100 - c["discount_value"]) / 100))
    if c["discount_type"] == "rs":
        return max(0, c["price"] - c["discount_value"])
    return c["price"]


def save_img(f):
    if not f or not f.filename:
        return None
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "Picture must be JPG, PNG or WEBP")
    name = uuid.uuid4().hex + ext
    with open(os.path.join("uploads", name), "wb") as out:
        out.write(f.file.read())
    return name


@app.on_event("startup")
def init():
    if DB_TYPE == "sqlite":
        init_sqlite_db()
    if not q("SELECT id FROM admin LIMIT 1", one=True):
        q("INSERT INTO admin(username,password_hash) VALUES(%s,%s)",
          ("admin", hp(os.getenv("ADMIN_PASSWORD", "1234"))), write=True)


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(d: Login):
    u = q("SELECT * FROM admin WHERE username=%s", (d.username,), one=True)
    if not u or hp(d.password, u["password_hash"].split("$")[0]) != u["password_hash"]:
        raise HTTPException(401, "Wrong username or password")
    t = secrets.token_hex(16)
    TOK.add(t)
    return {"token": t}


@app.get("/api/summary", dependencies=[Depends(auth)])
def summary():
    rows = q("SELECT section, COUNT(*) n, COALESCE(SUM(stock),0) stock, COALESCE(SUM(CASE WHEN stock<5 THEN 1 ELSE 0 END),0) low FROM cloths GROUP BY section")
    out = {s: {"n": 0, "stock": 0, "low": 0} for s in SEC}
    for r in rows:
        out[r["section"]] = {"n": int(r["n"]), "stock": int(r["stock"]), "low": int(r["low"])}
    return out


@app.get("/api/cloths", dependencies=[Depends(auth)])
def cloths(section: str = "", search: str = ""):
    s, a = "SELECT * FROM cloths WHERE 1=1", []
    if section in SEC:
        s += " AND section=%s"
        a.append(section)
    if search:
        s += " AND (name LIKE %s OR color LIKE %s OR size LIKE %s)"
        a += [f"%{search}%"] * 3
    return q(s + " ORDER BY id DESC", a)


@app.post("/api/cloths", dependencies=[Depends(auth)])
def add_cloth(section: str = Form(...), name: str = Form(...), color: str = Form(""), size: str = Form(""),
              price: int = Form(...), discount_type: str = Form("none"), discount_value: int = Form(0),
              stock: int = Form(0), image: UploadFile = File(None)):
    if section not in SEC:
        raise HTTPException(400, "Choose Men, Women or Kids")
    q("INSERT INTO cloths(section,name,color,size,price,discount_type,discount_value,stock,image,created_at) "
      "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
      (section, name.strip(), color.strip(), size.strip(), price, discount_type, discount_value, stock, save_img(image), str(now())), write=True)
    return {"ok": True}


@app.put("/api/cloths/{cid}", dependencies=[Depends(auth)])
def edit_cloth(cid: int, section: str = Form(...), name: str = Form(...), color: str = Form(""), size: str = Form(""),
               price: int = Form(...), discount_type: str = Form("none"), discount_value: int = Form(0),
               stock: int = Form(0), image: UploadFile = File(None)):
    old = q("SELECT image FROM cloths WHERE id=%s", (cid,), one=True)
    if not old or section not in SEC:
        raise HTTPException(400, "Cloth not found")
    img = save_img(image) or old["image"]
    q("UPDATE cloths SET section=%s,name=%s,color=%s,size=%s,price=%s,discount_type=%s,discount_value=%s,stock=%s,image=%s WHERE id=%s",
      (section, name.strip(), color.strip(), size.strip(), price, discount_type, discount_value, stock, img, cid), write=True)
    if img != old["image"] and old["image"]:
        try:
            os.remove(os.path.join("uploads", old["image"]))
        except OSError:
            pass
    return {"ok": True}


@app.delete("/api/cloths/{cid}", dependencies=[Depends(auth)])
def delete_cloth(cid: int):
    if q("SELECT id FROM orders WHERE cloth_id=%s LIMIT 1", (cid,), one=True):
        raise HTTPException(400, "This cloth has orders, so it cannot be deleted. Set its stock to 0 instead.")
    q("DELETE FROM cloths WHERE id=%s", (cid,), write=True)
    return {"ok": True}


class Order(BaseModel):
    cloth_id: int
    qty: int
    name: str
    phone: str
    city: str = ""
    address: str = ""
    pay_method: str
    tid: str = ""


@app.post("/api/orders", dependencies=[Depends(auth)])
def place_order(o: Order):
    c = q("SELECT * FROM cloths WHERE id=%s", (o.cloth_id,), one=True)
    if not c:
        raise HTTPException(404, "Cloth not found")
    if o.qty < 1 or o.qty > c["stock"]:
        raise HTTPException(400, f"Only {c['stock']} in stock")
    if o.pay_method not in PAY:
        raise HTTPException(400, "Choose a payment method")
    if o.pay_method != "cash" and not o.tid.strip():
        raise HTTPException(400, "Enter the transaction ID")
    if not o.name.strip() or not o.phone.strip():
        raise HTTPException(400, "Enter the customer name and phone")
    cust = q("INSERT INTO customers(name,phone,city,address) VALUES(%s,%s,%s,%s)",
             (o.name.strip(), o.phone.strip(), o.city.strip(), o.address.strip()), write=True)
    up = final_price(c)
    oid = q("INSERT INTO orders(cloth_id,customer_id,qty,unit_price,total,pay_method,tid,status,created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s)",
            (c["id"], cust, o.qty, up, up * o.qty, o.pay_method, o.tid.strip(), str(now())), write=True)
    q("UPDATE cloths SET stock=stock-%s WHERE id=%s", (o.qty, c["id"]), write=True)
    return {"order_id": oid}


@app.get("/api/orders", dependencies=[Depends(auth)])
def orders(search: str = ""):
    like = f"%{search}%"
    return q("SELECT o.*, c.name cloth, c.section, c.color, c.size, u.name customer, u.phone, u.city, u.address "
             "FROM orders o JOIN cloths c ON c.id=o.cloth_id JOIN customers u ON u.id=o.customer_id "
             "WHERE u.name LIKE %s OR u.phone LIKE %s OR o.id LIKE %s ORDER BY o.id DESC", (like, like, like))


@app.put("/api/orders/{oid}/status", dependencies=[Depends(auth)])
def order_status(oid: int, status: str):
    if status not in STATUS:
        raise HTTPException(400, "Wrong status")
    q("UPDATE orders SET status=%s WHERE id=%s", (status, oid), write=True)
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse("index.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)