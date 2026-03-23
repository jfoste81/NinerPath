# 🎓 NinerPath

NinerPath is a modern, full-stack student scheduling application. It uses a **Hybrid Data Architecture** to securely manage student data while simulating external university APIs for course catalogs.

## 🛠 Tech Stack
* **Frontend:** React, Vite, Tailwind CSS v3
* **Backend:** Python, FastAPI
* **Database & Auth:** PostgreSQL (via Supabase)
* **Mock Data:** Local JSON architecture

---

## 🚀 Getting Started (Local Development)

To run this project on your machine, you will need to run both the frontend and backend servers simultaneously.

### Prerequisites
* Node.js installed
* Python 3.8+ installed
* Ask Josh for the Supabase `.env` keys.

### 1. Clone the Repository
```bash
git clone [https://github.com/jfoste81/NinerPath.git](https://github.com/jfoste81/NinerPath.git)
cd NinerPath
```

### 2. Backend Setup (Terminal 1)
```bash
cd backend
python -m venv venv

# Activate the virtual environment
# On Windows: venv\Scripts\activate
# On Mac/Linux: source venv/bin/activate

pip install fastapi uvicorn supabase python-dotenv

# Create your environment file
touch .env
# Add SUPABASE_URL and SUPABASE_KEY to the .env file

# Start the server
uvicorn main:app --reload
```

### 3. Frontend Setup (Terminal 2)
```bash
cd frontend
npm install

# Create your environment file
touch .env
# Add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY to the .env file

# Start the frontend
npm run dev
```

### 4. Testing the App
1. Open `http://localhost:5173` in your browser.
2. Sign up with an email listed in `backend/data/student_history.json` (e.g., `sarah@uncc.edu`) to see dynamic mock data load automatically.
   1. Passwords to the accounts should be `Testing123!`