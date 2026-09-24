# Bhuvi Fashions - Python Flask Shopping Website

## What is included
- Bhuvi Fashions branding and logo watermark on every page
- Responsive fashion storefront
- Dynamic main categories and subcategories
- Women category with the supplied subcategories
- Correct category filtering: each subcategory shows only its own products
- Main categories without subcategories (for example Men/Kids) store products directly under that category
- Admin category manager: add, edit and delete categories/subcategories
- Product add/edit/delete with stock, discount and active/hidden status
- Multiple product photos in one upload
- Product video upload (MP4, WEBM, MOV, M4V)
- Product gallery with clickable thumbnails on the product page
- Media delete from admin product edit page
- Search across product name, description and category
- Customer registration/login, account and order history
- Shopping cart and checkout
- Admin order management

## Run in VS Code / Windows

1. Open this folder in VS Code.
2. Open Terminal.
3. Create a virtual environment:
   `python -m venv venv`
4. Activate it:
   `venv\Scripts\activate`
5. Install packages:
   `pip install -r requirements.txt`
6. Start:
   `python app.py`
7. Open:
   `http://127.0.0.1:5000`

## Admin
Open:
`http://127.0.0.1:5000/admin/login`

Default demo login:
- Username: `admin`
- Password: `admin123`

Change the credentials and Flask secret key before putting the website online.

## Category management
After logging into Admin:
- Dashboard -> Categories
- Add a main category with Parent = Main Category
- Add a subcategory by selecting a parent
- Rename categories directly in the table
- A category can be deleted only when it has no products and no active subcategories

## Product management
When adding a product:
- Select the main category first.
- If that category has subcategories, select the required subcategory.
- If it has no subcategories, the product is automatically stored under the main category itself.
- Use the Photos & Videos field to select multiple files at once.

The application automatically migrates the older SQLite database structure when it starts and keeps existing products.
