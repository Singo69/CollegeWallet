USE college_digital_wallet;

-- 1) Add full_name column (run ONCE)
-- ALTER TABLE users -- 
-- ADD COLUMN full_name VARCHAR(80); --

-- 2) Fill full names (run ONCE)
UPDATE users SET full_name = 'Ayudh Dahal'         WHERE username = 'Ayudh';
UPDATE users SET full_name = 'Subhash Budha Magar' WHERE username = 'Subhash';
UPDATE users SET full_name = 'Chetan Oli'          WHERE username = 'Chetan';
UPDATE users SET full_name = 'Aayush Bista'        WHERE username = 'Ayush';

-- 3) Add a merchant user (run ONCE)
INSERT INTO users (username, password, role, full_name, student_id, program, balance)
VALUES ('Canteen', 'canteen123', 'merchant', 'College Canteen', 'M-0001', 'College Canteen', 0.00);

-- 4) Create transactions table (run ONCE)
CREATE TABLE transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sender_user_id INT NOT NULL,
    receiver_user_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    method VARCHAR(20) DEFAULT 'ONLINE',
    status VARCHAR(20) DEFAULT 'SUCCESS',
    note VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_user_id) REFERENCES users(id),
    FOREIGN KEY (receiver_user_id) REFERENCES users(id)
);

-- 5) Verify
SELECT username, role, full_name, student_id, program, balance FROM users;
SELECT * FROM transactions ORDER BY created_at DESC;


USE college_digital_wallet;

-- A) Show database tables
SHOW TABLES;

-- B) Show schema (structure)
SHOW CREATE TABLE users;
SHOW CREATE TABLE transactions;

-- C) Show all users (data)
SELECT * FROM users;

-- D) Show all transactions with readable sender/receiver
SELECT
  t.id,
  t.amount,
  t.method,
  t.status,
  t.note,
  t.created_at,
  u1.username AS sender_username,
  u1.full_name AS sender_full_name,
  u1.student_id AS sender_student_id,
  u2.username AS receiver_username,
  u2.full_name AS receiver_full_name,
  u2.student_id AS receiver_student_id
FROM transactions t
JOIN users u1 ON u1.id = t.sender_user_id
JOIN users u2 ON u2.id = t.receiver_user_id
ORDER BY t.created_at DESC
LIMIT 100;

USE college_digital_wallet;

CREATE TABLE IF NOT EXISTS merchant_presence (
    merchant_username VARCHAR(50) PRIMARY KEY,
    network_id VARCHAR(64) NOT NULL,
    last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_network_last_seen (network_id, last_seen),

    CONSTRAINT fk_presence_merchant
      FOREIGN KEY (merchant_username) REFERENCES users(username)
      ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

USE college_digital_wallet;
SELECT * FROM transactions ORDER BY id DESC LIMIT 3;
SELECT username, balance FROM users WHERE username IN ('<student>', '<merchant>');




USE college_digital_wallet;
SELECT * FROM users;
SELECT id, username, role, full_name, student_id FROM users WHERE role='merchant';
INSERT INTO users (username, password, full_name, student_id, program, balance, role)
VALUES
('coffeespot', '1234', 'Coffee Spot', NULL, NULL, 10000, 'merchant'),
('stationery', '1234', 'Stationery', NULL, NULL, 10000, 'merchant');

USE college_digital_wallet;
USE college_digital_wallet;

-- Coffee Spot
UPDATE users
SET full_name = 'Coffee Spot',
    student_id = 'M-0002',
    program = 'Coffee Spot'
WHERE id > 0 AND username = 'coffeespot';

-- Stationery
UPDATE users
SET full_name = 'Stationery',
    student_id = 'M-0003',
    program = 'Stationery'
WHERE id > 0 AND username = 'stationery';
UPDATE users
SET balance = 5000.00
WHERE id > 0 AND role = 'student';

UPDATE users
SET balance = 20000.00
WHERE id > 0 AND role = 'merchant';

UPDATE users
SET student_id = 'M-0002', program = 'Coffee Spot'
WHERE username = 'coffeespot';

UPDATE users
SET student_id = 'M-0003', program = 'Stationery'
WHERE username = 'stationery';

SELECT id, username, role, student_id, balance FROM users ORDER BY id;

USE college_digital_wallet;

ALTER TABLE transactions
  ADD COLUMN client_tx_id VARCHAR(64) NULL;


CREATE UNIQUE INDEX uniq_client_tx_id ON transactions(client_tx_id);
