# College Digital Wallet

A secure campus wallet system that combines a digital student credential with online and offline token-based payments.

This project was built as my Final Year Project for BSc (Hons) Computer Networking and IT Security. My main focus was not only to build a working Android and backend application, but also to design and test security controls that are important in real payment and identity systems, such as replay protection, token expiry validation, encrypted local storage, backend-side verification, and audit logging.

---

## Overview

College Digital Wallet is a prototype system for a college environment where students can use one Android application to view their digital identity card, check wallet balance, make payments to campus merchants, and complete offline payments when internet access is not available.

The system has three main parts:

- Android student wallet application
- Flask backend API with MySQL database
- Browser-based merchant dashboard

For offline payment, the project uses Bluetooth Classic/RFCOMM. Offline transactions are stored in a local SQLite queue and synchronized with the backend when connectivity is restored. The backend still performs the final security checks before accepting synced transactions.

---

## Why I Built This

Many campus systems still depend on physical ID cards, cash, QR payments, or separate applications. Physical cards can be lost or copied, and online payment systems may fail when the network is weak.

I built this project to explore how a college can combine student identity and payment into one secure wallet system. Since I am focused on cybersecurity, I designed the project around secure payment flow, token protection, replay attack prevention, Android secure storage, and security testing evidence.

---

## Key Features

### Student App

- Student login
- Digital student ID display
- Wallet/token balance view
- Online payment to active merchants
- Offline Bluetooth payment
- Transaction history
- Secure offline token storage

### Merchant Dashboard

- Merchant login
- Start/stop online payment availability
- Start/stop offline Bluetooth receiver
- View transaction history
- View pending offline payments
- Sync offline queue to backend
- View basic analytics

### Security Features

- Password hashing and login validation
- HMAC-SHA256 signed payment tokens
- Online and offline token expiry validation
- Replay attack prevention using token status, nonce, and unique IDs
- Backend-side role and balance validation
- Encrypted Android local storage using `EncryptedSharedPreferences`
- SQLite offline queue with backend revalidation during sync
- Audit logging for login, token, payment, sync, and failed security events

---

## Technology Stack

| Area | Technology |
|---|---|
| Mobile App | Android, Kotlin, Jetpack Compose |
| API Client | Retrofit, Gson |
| Backend | Python, Flask |
| Main Database | MySQL |
| Local Offline Queue | SQLite |
| Offline Communication | Bluetooth Classic / RFCOMM |
| Android Secure Storage | `EncryptedSharedPreferences`, `MasterKey` |
| Cryptography | HMAC-SHA256, AES-256-GCM, AES-256-SIV |
| Merchant Portal | Flask web dashboard |
| Security Logging | `audit_events` table |

---

## System Architecture

```text
Student Android App
Kotlin + Jetpack Compose
        |
        | Retrofit API calls
        v
Flask Backend API  <------>  MySQL Database
Python                      users, transactions,
                            token tables, audit logs
        |
        v
Merchant Web Dashboard
Browser-based Flask portal
```

Offline payment flow:

```text
Student Android App
        |
        | Bluetooth Classic / RFCOMM
        v
Merchant Bluetooth Receiver
Python receiver
        |
        v
SQLite Offline Queue
        |
        | Sync when internet is available
        v
Flask Backend API
Revalidates token, expiry, signature,
balance, role, and duplicate transaction
        |
        v
MySQL Database
```

---

## Security Design

### 1. Token-Based Payment Flow

The online payment flow uses a two-step tokenized design.

1. The Android app requests a signed online token from the backend.
2. The backend creates a short-lived token and stores its status.
3. The Android app sends the token back to complete payment.
4. The backend verifies the token before accepting the payment.

A token includes values such as:

```text
token_id
nonce
amount
sender_username
merchant_username
expires_at
signature
status
```

This helps prevent the client from directly submitting a reusable payment request. The backend verifies that the token was created by the server and that it has not been changed, expired, or already used.

---

### 2. HMAC-SHA256 Token Signature

The project uses HMAC-SHA256 to protect the integrity of payment tokens.

For online payment, the signature is based on values such as:

```text
sender_username | merchant_username | amount | token_id | nonce | expires_at
```

For offline payment, the signature is based on values such as:

```text
sender_username | token_id | nonce | expires_at | max_amount
```

If an attacker changes the amount, merchant, expiry time, nonce, or token data, the recalculated signature will not match. In that case, the backend rejects the request.

Security value:

- Prevents payment amount tampering
- Prevents merchant tampering
- Protects token integrity
- Helps secure offline sync data before final backend approval

---

### 3. Replay Attack Prevention

A replay attack happens when someone captures a valid token or payment request and tries to use it again.

This project prevents replay attacks using:

- Unique `token_id`
- Unique `nonce`
- Token status tracking
- Token expiry check
- Unique offline `client_tx_id`
- Duplicate transaction checking
- Backend validation during offline sync
- Audit logging for failed replay attempts

After a token is used successfully, the backend changes its status from:

```text
ISSUED
```

to:

```text
USED
```

If the same token is submitted again, the backend rejects it.

Expected result:

```text
Token already used
```

For offline sync, the backend also checks whether the offline token or transaction ID has already been processed.

Expected result:

```text
Offline token already used
```

This proves that the same captured token cannot be reused to create another payment.

---

### 4. Expired Token Validation

Token expiry prevents old tokens from being used later.

The project uses two expiry approaches:

| Token Type | Purpose |
|---|---|
| Online token | Short lifetime because online payment should be completed quickly |
| Offline token | Longer lifetime because offline payment may need to be synced later |

During online payment or offline synchronization, the backend checks expiry time before accepting the transaction.

Expected results:

```text
Token expired
```

```text
Offline token expired
```

Security value:

- Tokens are not valid forever
- Stolen tokens have limited usefulness
- Expiry is checked on the backend, not only on the Android app
- Expired-token failures are recorded for testing evidence

---

### 5. Secure Android Local Storage

Offline tokens need to be stored on the Android device so that offline payment can work without internet. Storing these tokens in plain text would be risky.

To reduce this risk, I used Android secure storage with:

```kotlin
EncryptedSharedPreferences
```

The implementation uses:

```kotlin
MasterKey.KeyScheme.AES256_GCM
EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV
EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
```

Security value:

- Offline tokens are not stored as readable JSON
- Preference keys are encrypted
- Preference values are encrypted
- Tokens are stored per user
- Used tokens are removed after successful offline transfer
- Expired tokens can be cleared from local storage

I also tested the Android package storage and confirmed that the secure offline token file did not expose plain readable token values.

---

### 6. Offline Payment Security

Offline payment is the most important security part of this project because the payment can happen before the backend is available.

The offline flow is designed so that Bluetooth is only used as a transport method. It does not directly finalize the central payment.

Offline security flow:

1. Backend issues signed offline token pack while the user is online.
2. Android app stores tokens using encrypted local storage.
3. Student sends one offline token to the merchant through Bluetooth.
4. Merchant receiver stores the payment as pending in SQLite.
5. When internet returns, the merchant syncs the pending queue.
6. Backend revalidates the payment before inserting it into the main transaction history.

During sync, the backend checks:

```text
client_tx_id
token_id
token status
token expiry
token signature
student role
merchant role
student balance
duplicate transaction status
```

Security value:

- Offline mode does not bypass backend security
- The backend remains the final authority
- Duplicate, expired, tampered, or already-used offline payments are rejected
- Offline transactions are only confirmed after backend validation

---

### 7. Balance and Business Logic Validation

The backend checks the student wallet balance before accepting online or synced offline payments.

Expected result for invalid amount:

```text
Insufficient balance
```

Security value:

- Prevents overspending
- Does not trust only client-side balance
- Protects against manipulated payment requests
- Applies the same validation during offline sync

---

### 8. Audit Logging

Important security and payment actions are logged in the `audit_events` table.

Logged events include:

- Student login success and failure
- Merchant login success and failure
- Online token issue
- Online token consumption
- Replay rejection
- Expired-token rejection
- Offline token pack issue
- Offline sync success and failure
- Insufficient balance rejection
- Signature mismatch

Security value:

- Helps with debugging and investigation
- Provides evidence for security testing
- Shows why a payment was accepted or rejected
- Demonstrates security monitoring awareness

---

## Security Testing Performed

| Test | Risk Tested | Expected Result | Status |
|---|---|---|---|
| Invalid login test | Unauthorized access | Invalid credentials rejected | Implemented |
| Online replay test | Reuse same online token | `Token already used` | Implemented |
| Offline replay test | Reuse same offline token | `Offline token already used` | Implemented |
| Online expiry test | Use expired online token | `Token expired` | Implemented |
| Offline expiry test | Sync expired offline token | `Offline token expired` | Implemented |
| Token tampering test | Change amount, nonce, expiry, or signature | Token rejected | Implemented |
| Android storage test | Inspect offline token storage | Encrypted values observed | Implemented |
| Insufficient balance test | Pay more than available balance | Payment rejected | Implemented |
| Duplicate transaction test | Reuse same `client_tx_id` | Duplicate rejected | Implemented |
| Offline sync validation | Sync delayed transaction | Backend revalidates before accepting | Implemented |

---

## Main API Endpoints

| Method | Endpoint | Purpose | Security Relevance |
|---|---|---|---|
| `GET` | `/health` | Backend/database health check | Operational testing |
| `POST` | `/login` | Student login | Authentication and audit logging |
| `POST` | `/token/issue/online` | Issue online payment token | Tokenization |
| `POST` | `/pay/online/tokenized` | Consume online token | Replay, expiry, signature, and balance checks |
| `POST` | `/token/issue/offline-pack` | Issue offline token pack | Offline token security |
| `GET` | `/transactions/<username>` | View transaction history | Transaction visibility |
| `POST` | `/merchant/checkin` | Mark merchant active | Merchant discovery |
| `POST` | `/merchant/checkout` | Mark merchant inactive | Merchant control |
| `GET` | `/merchants?networkId=<network>` | Get nearby active merchants | Merchant selection |
| `POST` | `/offline/sync` | Sync offline payments | Offline token validation |
| `GET` | `/offline/queue/pending` | View pending offline queue | Queue management |
| `POST` | `/offline/queue/sync` | Sync merchant queue | Secure delayed processing |
| `POST` | `/offline/accepting/start` | Start Bluetooth receiver | Offline receiver control |
| `POST` | `/offline/accepting/stop` | Stop Bluetooth receiver | Offline receiver control |

---

## Database Design

Main MySQL tables:

| Table | Purpose |
|---|---|
| `users` | Stores student and merchant accounts, roles, balances, and password hash support |
| `transactions` | Stores successful and failed online/offline transaction records |
| `online_payment_tokens` | Stores online token metadata, status, expiry, nonce, and signature |
| `offline_payment_tokens` | Stores offline token metadata, status, expiry, nonce, and signature |
| `merchant_presence` | Tracks active merchants on the same local network |
| `audit_events` | Stores security and system activity logs |

Local SQLite table:

| Table | Purpose |
|---|---|
| `offline_payments` | Stores pending offline Bluetooth payments before backend synchronization |

---

## Project Structure

```text
college-digital-wallet/
├── README.md
├── .gitignore
├── .env.example
│
├── Backend/
│   ├── app.py
│   ├── offline_bluetooth_receiver.py
│   ├── offline_queue.py
│   ├── offline_receiver_control.py
│   └── requirements.txt
│
├── Database/
│   ├── setup.sql
│   └── migrations.sql
│
├── collegedigitalwallet_androidcode/
│   ├── app/
│   │   ├── src/main/java/com/example/collegedigitalwallet/
│   │   │   ├── MainActivity.kt
│   │   │   ├── AppNavigation.kt
│   │   │   ├── LoginScreen.kt
│   │   │   ├── WalletScreen.kt
│   │   │   ├── OnlinePaymentScreen.kt
│   │   │   ├── OfflinePaymentScreen.kt
│   │   │   ├── OfflineTokenStore.kt
│   │   │   ├── UserSession.kt
│   │   │   ├── api/
│   │   │   ├── model/
│   │   │   └── ui/theme/
│   │   └── build.gradle.kts
│   ├── build.gradle.kts
│   ├── settings.gradle.kts
│   └── gradle/
│
├── docs/
│   ├── architecture.png
│   └── security-testing.md
│
└── screenshots/
    ├── login.png
    ├── dashboard.png
    ├── online-payment.png
    ├── offline-payment.png
    ├── replay-test.png
    └── encrypted-storage.png
```

Note: Local runtime files such as `offline_queue.db`, log files, virtual environments, build folders, and real `.env` files should not be committed.

---

## Setup Guide

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/college-digital-wallet.git
cd college-digital-wallet
```

### 2. Set Up MySQL

Open MySQL and run:

```sql
SOURCE Database/setup.sql;
```

This creates the required database tables and demo records.

### 3. Configure Environment Variables

Create a `.env` file locally or export environment variables.

Example:

```bash
export DB_HOST="127.0.0.1"
export DB_USER="your_mysql_user"
export DB_PASSWORD="your_mysql_password"
export DB_NAME="college_digital_wallet"
export ONLINE_TOKEN_SECRET="change_this_online_secret"
export OFFLINE_TOKEN_SECRET="change_this_offline_secret"
```

For GitHub, only commit `.env.example`, not the real `.env` file.

Example `.env.example`:

```env
DB_HOST=127.0.0.1
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_NAME=college_digital_wallet
ONLINE_TOKEN_SECRET=change_this_online_secret
OFFLINE_TOKEN_SECRET=change_this_offline_secret
```

### 4. Install Backend Dependencies

```bash
cd Backend
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

If `requirements.txt` is not available, install the main packages manually:

```bash
pip install flask mysql-connector-python requests werkzeug pybluez2
```

### 5. Run Flask Backend

```bash
python app.py
```

Default local URL:

```text
http://127.0.0.1:5000
```

For a physical Android device, use the laptop/PC local network IP address.

Example:

```text
http://192.168.1.10:5000
```

### 6. Configure Android Base URL

Open:

```text
collegedigitalwallet_androidcode/app/src/main/java/com/example/collegedigitalwallet/api/RetrofitClient.kt
```

Set the backend URL:

```kotlin
private const val BASE_URL = "http://YOUR_LAPTOP_IP:5000/"
```

For Android emulator testing:

```kotlin
private const val BASE_URL = "http://10.0.2.2:5000/"
```

### 7. Run Android App

1. Open Android Studio.
2. Open the `collegedigitalwallet_androidcode` folder.
3. Let Gradle sync finish.
4. Run the app on an emulator or physical Android device.

---

## Demo Accounts

These accounts are for local testing only.

| Username | Password | Role |
|---|---|---|
| Ayudh | abc | Student |
| Subhash | def | Student |
| Chetan | ghi | Student |
| Ayush | jkl | Student |
| Canteen | canteen123 | Merchant |

Before any real deployment, demo credentials must be changed and secrets must be moved to environment variables.

---

## GitHub Upload Notes

For a professional GitHub repository, the project should be uploaded as source code, not as a single ZIP file.

Recommended files to include:

- Android source code
- Flask backend source code
- Database setup scripts
- `README.md`
- `.gitignore`
- `.env.example`
- Screenshots
- Architecture diagram
- Security testing notes

Recommended files to exclude:

- `.env`
- `venv/`
- `__pycache__/`
- `.gradle/`
- `build/`
- `app/build/`
- `local.properties`
- `*.apk`
- `*.log`
- `*.db`
- real secrets or personal data

---

## Why This Project Is Useful for My Cybersecurity Portfolio

This project shows practical security engineering, not only basic application development.

It demonstrates that I can:

- Build and secure an Android application
- Implement secure local storage
- Design token-based payment flows
- Use HMAC signatures for integrity protection
- Prevent replay attacks
- Validate expired tokens
- Secure offline transaction synchronization
- Perform backend-side validation instead of trusting the client
- Log important security events
- Test business logic issues such as insufficient balance and duplicate transactions
- Explain security decisions clearly with evidence

This makes the project useful for roles related to application security, mobile security, API security, secure software development, and cybersecurity testing.

---

## CV Description

**Secure College Digital Wallet**  
Built a secure Android-based campus wallet using Kotlin, Flask, MySQL, SQLite, and Bluetooth Classic. Implemented HMAC-SHA256 signed payment tokens, replay attack prevention, expired-token validation, encrypted Android local storage, audit logging, backend-side balance checks, and secure offline payment synchronization.

---

## Future Security Improvements

This project is an academic prototype. To make it stronger for production, these improvements should be added:

| Improvement | Benefit |
|---|---|
| HTTPS/TLS | Protects API traffic |
| Certificate pinning | Reduces mobile MITM risk |
| JWT access and refresh tokens | Improves API authentication |
| Rate limiting | Reduces brute-force login attempts |
| RBAC middleware | Strengthens student, merchant, and admin access separation |
| CSRF protection | Protects merchant web actions |
| Secure cookie flags | Improves web session security |
| Input validation schemas | Reduces malformed request and injection risk |
| Docker setup | Makes deployment and testing easier |
| SAST and dependency scanning | Adds DevSecOps practice |
| OWASP MASVS checklist | Improves Android security review |
| OWASP ASVS checklist | Improves backend security review |
| Remove debug routes in production | Reduces exposure of testing-only features |

---

## Security Notes

- This is an academic prototype and should not be used for real financial transactions without further security hardening.
- Local development may use HTTP for easier testing, but production must use HTTPS.
- Demo credentials must be replaced before deployment.
- Real `.env` files, secrets, database files, logs, and build files should not be committed to GitHub.
- Bluetooth pairing and device trust should be hardened before real-world use.
- Debug routes used for replay and expiry testing should be disabled in production.

---

## Author

**Ayudh Dahal**  
BSc (Hons) Computer Networking and IT Security  
Final Year Project — College Digital Wallet

---

## License

This project is for academic and portfolio use. Add a proper open-source license before public release.
