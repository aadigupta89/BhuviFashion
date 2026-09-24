import os
import sqlite3
import uuid
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bhuvi_fashions.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v"}

DEFAULT_CATEGORIES = [
    ("Women", None, 1),
    ("Indian & Fusion Wear", "Women", 1),
    ("Kurtas & Suits", "Women", 2),
    ("Kurtis, Tunics & Tops", "Women", 3),
    ("Sarees", "Women", 4),
    ("Ethnic Wear", "Women", 5),
    ("Leggings, Salwars & Churidars", "Women", 6),
    ("Skirts & Palazzos", "Women", 7),
    ("Dress Materials", "Women", 8),
    ("Lehenga Cholis", "Women", 9),
    ("Dupattas & Shawls", "Women", 10),
    ("Jackets", "Women", 11),
    ("Men", None, 20),
    ("Kids", None, 30),
    ("New Arrivals", None, 40),
    ("Accessories", None, 50),
]

app = Flask(__name__)
app.secret_key = "change-this-secret-key"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        category_id INTEGER,
        description TEXT,
        price REAL NOT NULL,
        discount REAL DEFAULT 0,
        stock INTEGER DEFAULT 0,
        image TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        phone TEXT,
        address TEXT,
        total REAL,
        status TEXT DEFAULT 'Pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        product_id INTEGER,
        quantity INTEGER,
        price REAL
    );
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        parent_id INTEGER,
        sort_order INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        UNIQUE(name, parent_id),
        FOREIGN KEY(parent_id) REFERENCES categories(id) ON DELETE RESTRICT
    );
    CREATE TABLE IF NOT EXISTS product_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        media_type TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    """)

    # Migrate older databases that did not have category_id.
    if "category_id" not in table_columns(conn, "products"):
        conn.execute("ALTER TABLE products ADD COLUMN category_id INTEGER")

    # Seed the original Bhuvi Fashions categories without overwriting admin changes.
    for name, parent_name, sort_order in DEFAULT_CATEGORIES:
        parent_id = None
        if parent_name:
            row = conn.execute("SELECT id FROM categories WHERE name=? AND parent_id IS NULL", (parent_name,)).fetchone()
            if row:
                parent_id = row["id"]
        existing = conn.execute(
            "SELECT id FROM categories WHERE name=? AND ((parent_id IS NULL AND ? IS NULL) OR parent_id=?)",
            (name, parent_id, parent_id),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO categories(name,parent_id,sort_order,active) VALUES(?,?,?,1)",
                (name, parent_id, sort_order),
            )

    # Link old products to the new category table by their stored category name.
    conn.execute("""
        UPDATE products
        SET category_id = (
            SELECT c.id FROM categories c WHERE c.name = products.category
            AND c.active=1 LIMIT 1
        )
        WHERE category_id IS NULL
    """)

    # If a legacy product has an image but no media row, expose that image in the gallery too.
    rows = conn.execute("SELECT id,image FROM products WHERE image IS NOT NULL AND image != ''").fetchall()
    for row in rows:
        exists = conn.execute("SELECT 1 FROM product_media WHERE product_id=? AND filename=?", (row["id"], row["image"])).fetchone()
        if not exists:
            ext = row["image"].rsplit(".", 1)[-1].lower() if "." in row["image"] else ""
            media_type = "video" if ext in VIDEO_EXTENSIONS else "image"
            conn.execute(
                "INSERT INTO product_media(product_id,filename,media_type,sort_order) VALUES(?,?,?,0)",
                (row["id"], row["image"], media_type),
            )

    conn.commit()
    conn.close()


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


def extension(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def save_media(file):
    if not file or not file.filename:
        return None
    ext = extension(file.filename)
    if ext not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        return None
    safe = secure_filename(file.filename)
    stem = secure_filename(os.path.splitext(safe)[0])[:60] or "media"
    filename = f"{stem}-{uuid.uuid4().hex[:12]}.{ext}"
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    media_type = "video" if ext in VIDEO_EXTENSIONS else "image"
    return filename, media_type


def get_categories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories WHERE active=1 ORDER BY sort_order,id").fetchall()
    conn.close()
    return rows


def get_category_tree():
    rows = get_categories()
    parents = [r for r in rows if r["parent_id"] is None]
    children = {}
    for row in rows:
        if row["parent_id"] is not None:
            children.setdefault(row["parent_id"], []).append(row)
    return [(p, children.get(p["id"], [])) for p in parents]


@app.context_processor
def inject_navigation():
    return {"category_tree": get_category_tree()}


@app.route("/")
def index():
    conn = get_db()
    products = conn.execute(
        "SELECT * FROM products WHERE active=1 ORDER BY id DESC LIMIT 12"
    ).fetchall()
    conn.close()
    return render_template("index.html", products=products)


@app.route("/shop")
def shop():
    category = request.args.get("category", "").strip()
    q = request.args.get("q", "").strip()
    conn = get_db()
    sql = """
        SELECT p.* FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.active=1
    """
    params = []

    if category:
        selected = conn.execute(
            "SELECT * FROM categories WHERE name=? AND active=1 ORDER BY CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END LIMIT 1",
            (category,),
        ).fetchone()
        if selected:
            child_rows = conn.execute(
                "SELECT id FROM categories WHERE parent_id=? AND active=1 ORDER BY sort_order,id",
                (selected["id"],),
            ).fetchall()
            ids = [selected["id"]] + [r["id"] for r in child_rows]
            placeholders = ",".join("?" for _ in ids)
            sql += f" AND p.category_id IN ({placeholders})"
            params.extend(ids)
        else:
            # Backward compatibility for a product entered with a category name
            # that has not yet been migrated to the category table.
            sql += " AND p.category=?"
            params.append(category)

    if q:
        sql += " AND (p.name LIKE ? OR p.description LIKE ? OR p.category LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]

    sql += " ORDER BY p.id DESC"
    products = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template("shop.html", products=products, category=category, q=q)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
    media = conn.execute("SELECT * FROM product_media WHERE product_id=? ORDER BY sort_order,id", (product_id,)).fetchall()
    conn.close()
    if not product:
        return "Product not found", 404
    return render_template("product_detail.html", product=product, media=media)


@app.route("/cart")
def cart():
    cart_items = session.get("cart", {})
    ids = [int(x) for x in cart_items.keys()]
    products = []
    total = 0
    if ids:
        conn = get_db()
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT * FROM products WHERE id IN ({placeholders})", ids).fetchall()
        conn.close()
        for p in rows:
            qty = int(cart_items.get(str(p["id"]), 0))
            sale_price = p["price"] * (1 - (p["discount"] or 0) / 100)
            total += sale_price * qty
            products.append({"product": p, "qty": qty, "sale_price": sale_price})
    return render_template("cart.html", items=products, total=total)


@app.post("/cart/add/<int:product_id>")
def add_to_cart(product_id):
    cart = session.get("cart", {})
    key = str(product_id)
    cart[key] = int(cart.get(key, 0)) + 1
    session["cart"] = cart
    flash("Product added to cart.", "success")
    return redirect(request.referrer or url_for("shop"))


@app.post("/cart/remove/<int:product_id>")
def remove_from_cart(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if not session.get("user_id"):
        flash("Please login or create an account before checkout.", "danger")
        return redirect(url_for("login"))
    if request.method == "POST":
        cart_items = session.get("cart", {})
        if not cart_items:
            return redirect(url_for("cart"))
        conn = get_db()
        ids = [int(x) for x in cart_items.keys()]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT * FROM products WHERE id IN ({placeholders})", ids).fetchall()
        total = 0
        for p in rows:
            qty = int(cart_items[str(p["id"])])
            total += p["price"] * (1 - (p["discount"] or 0) / 100) * qty
        cur = conn.execute(
            "INSERT INTO orders(customer_name,phone,address,total) VALUES(?,?,?,?)",
            (request.form["customer_name"], request.form["phone"], request.form["address"], total)
        )
        order_id = cur.lastrowid
        for p in rows:
            qty = int(cart_items[str(p["id"])])
            sale_price = p["price"] * (1 - (p["discount"] or 0) / 100)
            conn.execute(
                "INSERT INTO order_items(order_id,product_id,quantity,price) VALUES(?,?,?,?)",
                (order_id, p["id"], qty, sale_price)
            )
            conn.execute("UPDATE products SET stock=MAX(stock-?,0) WHERE id=?", (qty, p["id"]))
        conn.commit()
        conn.close()
        session["cart"] = {}
        return render_template("order_success.html", order_id=order_id)
    return render_template("checkout.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("account"))
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("register.html")
        conn = get_db()
        try:
            conn.execute("INSERT INTO users(name,email,phone,password) VALUES(?,?,?,?)",
                         (name, email, phone, generate_password_hash(password)))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash("This email is already registered. Please login.", "danger")
            return render_template("register.html")
        conn.close()
        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("account"))
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("account"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    return redirect(url_for("index"))


@app.route("/account")
def account():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    conn = get_db()
    user = conn.execute("SELECT id,name,email,phone,created_at FROM users WHERE id=?",
                        (session["user_id"],)).fetchone()
    orders = []
    if user:
        orders = conn.execute("SELECT * FROM orders WHERE phone=? ORDER BY id DESC",
                              (user["phone"],)).fetchall()
    conn.close()
    return render_template("account.html", user=user, orders=orders)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "admin123":
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
    low_stock = conn.execute("SELECT COUNT(*) FROM products WHERE stock <= 5").fetchone()[0]
    category_count = conn.execute("SELECT COUNT(*) FROM categories WHERE active=1").fetchone()[0]
    media_count = conn.execute("SELECT COUNT(*) FROM product_media").fetchone()[0]
    conn.close()
    return render_template("admin/dashboard.html", product_count=product_count,
                           order_count=order_count, sales=sales, low_stock=low_stock,
                           category_count=category_count, media_count=media_count)


@app.route("/admin/categories", methods=["GET", "POST"])
@admin_required
def admin_categories():
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        parent_id = request.form.get("parent_id") or None
        if not name:
            flash("Category name is required.", "danger")
        else:
            try:
                parent_id = int(parent_id) if parent_id else None
                if parent_id:
                    parent = conn.execute("SELECT id FROM categories WHERE id=? AND active=1", (parent_id,)).fetchone()
                    if not parent:
                        raise ValueError("Invalid parent category")
                max_order = conn.execute(
                    "SELECT COALESCE(MAX(sort_order),0) FROM categories WHERE parent_id IS ?", (parent_id,)
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO categories(name,parent_id,sort_order,active) VALUES(?,?,?,1)",
                    (name, parent_id, max_order + 1),
                )
                conn.commit()
                flash("Category added successfully.", "success")
            except (sqlite3.IntegrityError, ValueError):
                flash("This category already exists under the selected parent or the parent is invalid.", "danger")
        conn.close()
        return redirect(url_for("admin_categories"))

    rows = conn.execute("""
        SELECT c.*, p.name AS parent_name,
               (SELECT COUNT(*) FROM categories x WHERE x.parent_id=c.id AND x.active=1) AS child_count,
               (SELECT COUNT(*) FROM products pr WHERE pr.category_id=c.id) AS product_count
        FROM categories c
        LEFT JOIN categories p ON p.id=c.parent_id
        WHERE c.active=1
        ORDER BY COALESCE(p.sort_order, c.sort_order), CASE WHEN c.parent_id IS NULL THEN 0 ELSE 1 END, c.sort_order, c.id
    """).fetchall()
    parents = conn.execute("SELECT * FROM categories WHERE parent_id IS NULL AND active=1 ORDER BY sort_order,id").fetchall()
    conn.close()
    return render_template("admin/categories.html", categories=rows, parents=parents)


@app.post("/admin/categories/edit/<int:category_id>")
@admin_required
def edit_category(category_id):
    name = request.form.get("name", "").strip()
    conn = get_db()
    category = conn.execute("SELECT * FROM categories WHERE id=? AND active=1", (category_id,)).fetchone()
    if not category or not name:
        flash("Invalid category update.", "danger")
    else:
        try:
            conn.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))
            conn.execute("UPDATE products SET category=? WHERE category_id=?", (name, category_id))
            conn.commit()
            flash("Category updated successfully.", "success")
        except sqlite3.IntegrityError:
            flash("A category with this name already exists at this level.", "danger")
    conn.close()
    return redirect(url_for("admin_categories"))


@app.post("/admin/categories/delete/<int:category_id>")
@admin_required
def delete_category(category_id):
    conn = get_db()
    category = conn.execute("SELECT * FROM categories WHERE id=? AND active=1", (category_id,)).fetchone()
    if not category:
        flash("Category not found.", "danger")
    else:
        children = conn.execute("SELECT COUNT(*) FROM categories WHERE parent_id=? AND active=1", (category_id,)).fetchone()[0]
        products = conn.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (category_id,)).fetchone()[0]
        if children or products:
            flash("This category cannot be deleted while it has subcategories or products. Move/delete those items first.", "danger")
        else:
            conn.execute("UPDATE categories SET active=0 WHERE id=?", (category_id,))
            conn.commit()
            flash("Category deleted.", "success")
    conn.close()
    return redirect(url_for("admin_categories"))


@app.route("/admin/products")
@admin_required
def admin_products():
    conn = get_db()
    products = conn.execute("""
        SELECT p.*, c.name AS category_name,
               (SELECT COUNT(*) FROM product_media pm WHERE pm.product_id=p.id) AS media_count
        FROM products p
        LEFT JOIN categories c ON c.id=p.category_id
        ORDER BY p.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin/products.html", products=products)


def resolve_product_category(form):
    category_id = form.get("category_id", "").strip()
    if not category_id:
        return None
    conn = get_db()
    selected = conn.execute("SELECT * FROM categories WHERE id=? AND active=1", (category_id,)).fetchone()
    if not selected:
        conn.close()
        return None
    children = conn.execute("SELECT COUNT(*) FROM categories WHERE parent_id=? AND active=1", (selected["id"],)).fetchone()[0]
    # A category with subcategories must use one of its subcategories for products.
    if children:
        conn.close()
        return None
    conn.close()
    return selected


def upload_product_media(conn, product_id, files):
    existing_count = conn.execute("SELECT COUNT(*) FROM product_media WHERE product_id=?", (product_id,)).fetchone()[0]
    first_image = None
    sort_order = existing_count
    for file in files:
        saved = save_media(file)
        if not saved:
            continue
        filename, media_type = saved
        conn.execute(
            "INSERT INTO product_media(product_id,filename,media_type,sort_order) VALUES(?,?,?,?)",
            (product_id, filename, media_type, sort_order),
        )
        sort_order += 1
        if media_type == "image" and first_image is None:
            first_image = filename
    return first_image


@app.route("/admin/products/add", methods=["GET", "POST"])
@admin_required
def add_product():
    conn = get_db()
    categories = conn.execute("SELECT * FROM categories WHERE active=1 ORDER BY sort_order,id").fetchall()
    parents = conn.execute("SELECT * FROM categories WHERE parent_id IS NULL AND active=1 ORDER BY sort_order,id").fetchall()
    if request.method == "POST":
        selected = resolve_product_category(request.form)
        if not selected:
            conn.close()
            flash("Please select a valid category. If the category has subcategories, select the subcategory.", "danger")
            return redirect(url_for("add_product"))

        try:
            cur = conn.execute("""
                INSERT INTO products(name,category,category_id,description,price,discount,stock,image,active)
                VALUES(?,?,?,?,?,?,?,?,1)
            """, (
                request.form["name"].strip(), selected["name"], selected["id"],
                request.form.get("description", "").strip(),
                float(request.form["price"]), float(request.form.get("discount") or 0),
                int(request.form.get("stock") or 0), None
            ))
            product_id = cur.lastrowid
            first_image = upload_product_media(conn, product_id, request.files.getlist("media"))
            if first_image:
                conn.execute("UPDATE products SET image=? WHERE id=?", (first_image, product_id))
            conn.commit()
            conn.close()
            flash("Product added successfully.", "success")
            return redirect(url_for("admin_products"))
        except (ValueError, sqlite3.Error):
            conn.rollback()
            conn.close()
            flash("Please check the product details and try again.", "danger")
            return redirect(url_for("add_product"))
    conn.close()
    return render_template("admin/product_form.html", product=None, categories=categories, parents=parents, media=[], selected_parent_id=None)


@app.route("/admin/products/edit/<int:product_id>", methods=["GET", "POST"])
@admin_required
def edit_product(product_id):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not product:
        conn.close()
        return "Product not found", 404
    categories = conn.execute("SELECT * FROM categories WHERE active=1 ORDER BY sort_order,id").fetchall()
    parents = conn.execute("SELECT * FROM categories WHERE parent_id IS NULL AND active=1 ORDER BY sort_order,id").fetchall()
    media = conn.execute("SELECT * FROM product_media WHERE product_id=? ORDER BY sort_order,id", (product_id,)).fetchall()

    if request.method == "POST":
        selected = resolve_product_category(request.form)
        if not selected:
            conn.close()
            flash("Please select a valid category. If the category has subcategories, select the subcategory.", "danger")
            return redirect(url_for("edit_product", product_id=product_id))
        try:
            conn.execute("""UPDATE products SET name=?,category=?,category_id=?,description=?,price=?,
                discount=?,stock=?,active=? WHERE id=?""", (
                request.form["name"].strip(), selected["name"], selected["id"],
                request.form.get("description", "").strip(), float(request.form["price"]),
                float(request.form.get("discount") or 0), int(request.form.get("stock") or 0),
                1 if request.form.get("active") else 0, product_id
            ))
            first_image = upload_product_media(conn, product_id, request.files.getlist("media"))
            if first_image and not product["image"]:
                conn.execute("UPDATE products SET image=? WHERE id=?", (first_image, product_id))
            conn.commit()
            conn.close()
            flash("Product updated successfully.", "success")
            return redirect(url_for("admin_products"))
        except (ValueError, sqlite3.Error):
            conn.rollback()
            conn.close()
            flash("Please check the product details and try again.", "danger")
            return redirect(url_for("edit_product", product_id=product_id))

    selected_parent_id = None
    if product["category_id"]:
        selected_category = next((c for c in categories if c["id"] == product["category_id"]), None)
        if selected_category:
            selected_parent_id = selected_category["parent_id"] or selected_category["id"]
    conn.close()
    return render_template("admin/product_form.html", product=product, categories=categories, parents=parents, media=media, selected_parent_id=selected_parent_id)


@app.post("/admin/products/media/delete/<int:media_id>")
@admin_required
def delete_product_media(media_id):
    conn = get_db()
    media = conn.execute("SELECT * FROM product_media WHERE id=?", (media_id,)).fetchone()
    if not media:
        conn.close()
        flash("Media not found.", "danger")
        return redirect(url_for("admin_products"))
    product_id = media["product_id"]
    path = os.path.join(UPLOAD_FOLDER, media["filename"])
    conn.execute("DELETE FROM product_media WHERE id=?", (media_id,))
    remaining = conn.execute("SELECT * FROM product_media WHERE product_id=? ORDER BY sort_order,id", (product_id,)).fetchall()
    new_image = next((m["filename"] for m in remaining if m["media_type"] == "image"), None)
    conn.execute("UPDATE products SET image=? WHERE id=?", (new_image, product_id))
    conn.commit()
    conn.close()
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    flash("Media deleted.", "success")
    return redirect(url_for("edit_product", product_id=product_id))


@app.post("/admin/products/delete/<int:product_id>")
@admin_required
def delete_product(product_id):
    conn = get_db()
    media = conn.execute("SELECT filename FROM product_media WHERE product_id=?", (product_id,)).fetchall()
    conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    conn.close()
    for row in media:
        path = os.path.join(UPLOAD_FOLDER, row["filename"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    flash("Product deleted.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    conn = get_db()
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin/orders.html", orders=orders)


@app.post("/admin/orders/status/<int:order_id>")
@admin_required
def update_order_status(order_id):
    status = request.form["status"]
    conn = get_db()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_orders"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
