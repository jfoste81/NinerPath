# NinerPath

NinerPath is a modern, full-stack student scheduling application designed to streamline degree auditing and course registration. It utilizes a decoupled client-server architecture, securely managing user authentication and saved schedules while simulating external university APIs through a local JSON mock data architecture.

## Tech Stack
* **Frontend:** React, Vite, Tailwind CSS v3
* **Backend:** Python, FastAPI
* **Database & Authentication:** PostgreSQL (via Supabase)
* **Data Layer:** Local JSON architecture (simulated course catalogs and student histories)

---

## Architecture Overview

The application follows a decoupled client-server model, ensuring horizontal scalability and strict separation of concerns.

### Backend (FastAPI)
The backend utilizes a Layered/Service-Oriented Architecture (SOA):
* **Routing & Presentation:** (`main.py`, `api_schemas.py`) Uses Pydantic for strict data validation and FastAPI for RESTful routing.
* **Business Logic:** (`scheduler_service.py`, `degree_audit.py`, `catalog.py`) Handles the 0/1 Knapsack Dynamic Programming algorithms for schedule generation, prerequisite enforcement, and degree deficit calculations.
* **Data Access:** (`data_access.py`, `persistence.py`) Manages in-memory caching for JSON reads to prevent disk I/O bottlenecks and handles Supabase database interactions.

### Frontend (React)
The frontend employs a Component-Driven Architecture:
* **Data Layer (Custom Hooks):** Encapsulates all side effects, fetch logic, and loading/error states (e.g., `useScheduleGeneration`, `useDashboardData`).
* **Container Layer:** Page-level orchestrators (`SchedulePage.jsx`, `DegreeHomePage.jsx`) that fetch data and distribute it to child components.
* **Presentation Layer:** Isolated UI components (`TimePreferencePanel.jsx`, `CombinationSelector.jsx`) that handle rendering and local interactions to prevent application-wide re-renders.