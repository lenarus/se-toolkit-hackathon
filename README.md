# CF Compare - Codeforces User Comparison Tool

A web application that allows users to enter multiple Codeforces handles and compare their performance side by side.

## 📋 Features

- ✅ Compare 2-5 Codeforces users simultaneously
- ✅ View current rating, rank, and max rating
- ✅ Count solved problems (unique problems only)
- ✅ Save comparison results to PostgreSQL database
- ✅ Retrieve saved comparisons via API
- ✅ Clean, responsive UI
- ✅ Fully Dockerized setup

## 📁 Project Structure

```
se-toolkit-hackathon/
├── backend/                    # FastAPI backend
│   ├── main.py                 # Main application with routes
│   └── requirements.txt        # Python dependencies
├── frontend/                   # Static frontend files
│   ├── index.html              # Main HTML page
│   ├── style.css               # Styles
│   └── app.js                  # JavaScript logic
├── docker/                     # Docker configuration
│   ├── Dockerfile.backend      # Backend Docker image
│   ├── Dockerfile.frontend     # Frontend Docker image
│   ├── nginx.conf              # Nginx configuration
│   └── init-db.sql             # Database initialization
├── docker-compose.yml          # Docker Compose configuration
├── .env                        # Environment variables
├── .env.example                # Example environment file
└── README.md                   # This file
```

## 🚀 Quick Start (Docker)

### Prerequisites

- Docker and Docker Compose installed
- Git (optional)

### Step 1: Clone or Navigate to Project

```bash
cd /root/se-toolkit-hackathon
```

### Step 2: Configure Environment Variables

The `.env` file is already configured with API credentials. If you want to use your own Codeforces API credentials:

1. Get API key and secret from: https://codeforces.com/settings/api
2. Edit `.env` file:

```bash
nano .env
```

### Step 3: Build and Run with Docker Compose

```bash
# Build and start all services
docker-compose up --build

# Or run in detached mode (background)
docker-compose up --build -d
```

This will:
- Build the backend image (Python + FastAPI)
- Build the frontend image (Nginx)
- Start PostgreSQL database
- Create all necessary tables
- Connect all services together

### Step 4: Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs (Swagger UI)
- **Database**: localhost:5432

### Step 5: Stop the Application

```bash
# Stop all containers
docker-compose down

# Stop and remove volumes (deletes database data)
docker-compose down -v
```

## 🔧 API Endpoints

### 1. Compare Users

**GET** `/compare?handles=user1,user2,user3`

Compare multiple Codeforces users.

**Example:**

```bash
curl "http://localhost:8000/compare?handles=tourist,petr"
```

**Response:**

```json
{
  "users": [
    {
      "handle": "tourist",
      "rating": 3800,
      "rank": "legendary grandmaster",
      "maxRating": 3800,
      "maxRank": "legendary grandmaster",
      "solved_count": 2500
    },
    {
      "handle": "petr",
      "rating": 3200,
      "rank": "grandmaster",
      "maxRating": 3300,
      "maxRank": "legendary grandmaster",
      "solved_count": 1800
    }
  ],
  "saved_id": 1
}
```

### 2. Health Check

**GET** `/health`

Check if the backend is running.

```bash
curl http://localhost:8000/health
```

### 3. Get Saved Comparisons

**GET** `/comparisons?limit=10`

Get recent saved comparisons.

```bash
curl "http://localhost:8000/comparisons?limit=5"
```

### 4. Get Specific Comparison

**GET** `/comparisons/{id}`

Get a specific comparison by ID.

```bash
curl http://localhost:8000/comparisons/1
```

## 💾 Database Schema

The `comparisons` table stores all comparison results:

```sql
CREATE TABLE comparisons (
    id SERIAL PRIMARY KEY,
    handles TEXT NOT NULL,           -- Comma-separated handles
    result TEXT NOT NULL,            -- JSON string of results
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

## 🛠️ Development (Without Docker)

If you prefer to run the project locally without Docker:

### Backend

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file with database URL (for local PostgreSQL)
echo "DATABASE_URL=postgresql://cfuser:cfpassword@localhost:5432/cfcompare" > .env

# Run the application
uvicorn main:app --reload
```

### Frontend

Open `frontend/index.html` in a browser, or serve it with a simple HTTP server:

```bash
cd frontend
python -m http.server 3000
```

### Database

Make sure PostgreSQL is running and create the database:

```bash
# Create database
createdb -U cfuser cfcompare

# Run initialization script
psql -U cfuser -d cfcompare -f docker/init-db.sql
```

## 🐛 Troubleshooting

### Backend can't connect to database

- Make sure the database container is healthy: `docker-compose ps`
- Check database logs: `docker-compose logs db`
- Verify `DATABASE_URL` in docker-compose.yml uses service name `db`, not `localhost`

### Frontend shows "Failed to fetch data"

- Check if backend is running: `curl http://localhost:8000/health`
- Check backend logs: `docker-compose logs backend`
- Verify handles are valid Codeforces usernames

### Port already in use

If ports 3000, 8000, or 5432 are already in use, edit `docker-compose.yml` and change the port mappings:

```yaml
ports:
  - "8080:80"  # Change frontend to port 8080
```

## 📝 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_USER` | Database username | `cfuser` |
| `POSTGRES_PASSWORD` | Database password | `cfpassword` |
| `POSTGRES_DB` | Database name | `cfcompare` |
| `API_KEY` | Codeforces API key | (from .env) |
| `API_SECRET` | Codeforces API secret | (from .env) |

## 🔐 Codeforces API Integration

This application uses the Codeforces API with optional authentication:

- **user.info** - Get user profile information
- **user.rating** - Get rating history
- **user.status** - Get submissions to count solved problems

API credentials are stored in `.env` and passed securely to the backend.

## 📄 License

MIT License - Feel free to use and modify!

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

**Built with:** FastAPI, PostgreSQL, Nginx, Docker Compose
**Data source:** [Codeforces API](https://codeforces.com/api)
