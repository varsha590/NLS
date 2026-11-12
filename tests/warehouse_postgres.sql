CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price NUMERIC);
CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, product_id INTEGER, quantity INTEGER, FOREIGN KEY (product_id) REFERENCES products(id));
