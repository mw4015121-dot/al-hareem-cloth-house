CREATE DATABASE IF NOT EXISTS alhareem CHARACTER SET utf8mb4;
USE alhareem;

CREATE TABLE IF NOT EXISTS admin (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS cloths (
  id INT AUTO_INCREMENT PRIMARY KEY,
  section ENUM('men','women','kids') NOT NULL,
  name VARCHAR(120) NOT NULL,
  color VARCHAR(50) DEFAULT '',
  size VARCHAR(60) DEFAULT '',
  price INT NOT NULL,
  discount_type ENUM('none','percent','rs') DEFAULT 'none',
  discount_value INT DEFAULT 0,
  stock INT DEFAULT 0,
  image VARCHAR(255),
  created_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  phone VARCHAR(20) NOT NULL,
  city VARCHAR(60) DEFAULT '',
  address VARCHAR(255) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cloth_id INT NOT NULL,
  customer_id INT NOT NULL,
  qty INT NOT NULL,
  unit_price INT NOT NULL,
  total INT NOT NULL,
  pay_method VARCHAR(20) NOT NULL,
  tid VARCHAR(60) DEFAULT '',
  status VARCHAR(20) DEFAULT 'pending',
  created_at DATETIME NOT NULL,
  FOREIGN KEY (cloth_id) REFERENCES cloths(id),
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);
