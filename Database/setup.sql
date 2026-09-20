-- ===== TEST RESET SCRIPT (SAFE TO RUN MULTIPLE TIMES) =====

CREATE DATABASE IF NOT EXISTS college_digital_wallet;
USE college_digital_wallet;


-- Recreate users
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username   VARCHAR(50) NOT NULL UNIQUE,
    password   VARCHAR(50) NOT NULL,
    role       VARCHAR(20) DEFAULT 'student',
    full_name  VARCHAR(80),
    student_id VARCHAR(30),
    program    VARCHAR(100),
    balance    DECIMAL(10,2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recreate transactions
CREATE TABLE transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sender_user_id   INT NOT NULL,
    receiver_user_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    method VARCHAR(20) NOT NULL DEFAULT 'ONLINE',
    status VARCHAR(20) NOT NULL DEFAULT 'SUCCESS',
    note VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (sender_user_id) REFERENCES users(id),
    FOREIGN KEY (receiver_user_id) REFERENCES users(id)
);

-- Insert students + merchant
INSERT INTO users (username, password, role, full_name, student_id, program, balance) VALUES
('Ayudh',   'abc', 'student',  'Ayudh Dahal',         'NP01NTA4230180', 'BSc (Hons) Networking & IT Security', 2000.09),
('Subhash', 'def', 'student',  'Subhash Budha Magar', 'NP01NTA4230181', 'BSc (Hons) Networking & IT Security', 1500.50),
('Chetan',  'ghi', 'student',  'Chetan Oli',          'NP01NTA4230182', 'BSc (Hons) Networking & IT Security', 1250.00),
('Ayush',   'jkl', 'student',  'Aayush Bista',        'NP01NTA4230183', 'BSc (Hons) Networking & IT Security', 1750.75),
('Canteen', 'canteen123', 'merchant', 'College Canteen', 'M-0001', 'College Canteen', 0.00);

-- Quick check
USE college_digital_wallet;
SHOW tables;
SELECT * FROM users;
SELECT * FROM transactions;
SELECT * FROM merchant_presence;
