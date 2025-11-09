# MyMDB - Backend course project

## What’s in my solution

* **Models**

  * `Movie(title, poster, description, director→FK, release_year, main_actors↔M2M, genres↔M2M)`
  * `Director(first_name, last_name)`
  * `Actor(first_name, last_name)`
  * `Genre(name)`
  * `Rating(user→FK, movie→FK, score)` with a unique constraint on `(user, movie)`.
  * `Review(user→FK, movie→FK, title, body)` with a unique constraint on `(user, movie)`.
* **User Authentication**

  * Standard Django `User` model for authentication.
  * **Signup**: `accounts/signup.html` with `UserCreationForm`.
  * **Login/Logout**: `accounts/login.html` and standard Django views.
  * Display of user status in the header (`base.html`).
* **Frontend Views (Function-Based)**

  * **Movie List (`movie_list`)**:
    * Displays a paginated grid of movies (25 per page).
    * Supports sorting by title, release year, and newest.
    * Uses `select_related` and `prefetch_related` for efficient querying.
  * **Movie Details (`movie_details`)**:
    * Full movie information.
    * Shows average rating, rating distribution, and community reviews.
    * AJAX-powered star rating submission.
    * Form for submitting new reviews.
    * Displays up to 5 similar movies based on shared genres.
* **Admin**

  * All six models registered in Django Admin for easy add/edit/browse.
* **Data collection (Jupyter Notebook)**

  * Fetches popular movies from TMDB by genre.
  * **Skips adult titles**, **deduplicates** across genres, and **validates poster downloads**.
  * Saves posters locally (manually moved to `media/posters/`) and writes `tmdb_movies.json` with only the fields my app needs.
  * Keeps TMDB IDs **only in the JSON** (for debugging/re-runs); not stored in the DB.
* **Import endpoint (function-based DRF view)**

  * `POST /api/import_tmdb_movies/` (admin-only via `IsAdminUser`).
  * Accepts either raw JSON or an uploaded JSON file.
  * Upserts movies by `(title, release_year)`.
  * Splits names and creates/links `Director`, creates/links up to **4** `Actor`s, and attaches **all** `Genre`s (M2M).
  * Assigns posters by **relative path** if the file exists in the Django default storage (local `MEDIA_ROOT/posters/` in dev, S3 in prod).
* **Result of my import run - tmdb_movies.json**

  * Created **119** movies, **19** genres, **112** directors, **422** actors.

* **AI Chatbot (Gemini/Bedrock)**

  * **Backend**:
    * A view `chatbot_api` that receives user messages and chat history.
    * Provider is selected by env var `AI_PROVIDER` (dev: `gemini`, prod on EC2: `bedrock`).
    * Two-step flow: (1) parse intent/criteria, (2) query DB and generate a short reply with up to 3 recommendations.
  * **Frontend**:
    * A chat widget in `base.html`.
    * `static/js/chat.js` handles the communication with the `chatbot_api` endpoint.
    * Displays AI responses and movie recommendations with links to the movie details page.



## Phase 1 – Local / Dev Setup Instructions

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/yanivraveh/mymdb
    cd mymdb
    ```

2.  **Create and Activate a Virtual Environment**
    *   **For Windows:**
        ```bash
        python -m venv .venv
        .\.venv\Scripts\activate
        ```
    *   **For macOS/Linux:**
        ```bash
        python3 -m venv .venv
        source .venv/bin/activate
        ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Up Environment Variables**
    *   Navigate to the inner `mymdb` directory (the one with `manage.py`).
    *   Create a file named `.env` in that same directory.
    *   Add your Gemini API key to this file:
        ```
        GEMINI_API_KEY="your_api_key_here"
        ```

5.  **Database Migrations**
    *   **Note**: The provided database `db.sqlite3` **is already migrated**. 
        * Running this command will show "No migrations to apply." 
        * It would only be necessary if you deleted the database file to start with an empty one.
    ```bash
    python manage.py migrate
    ```

6.  **Create an Admin Superuser**
    *   You'll need an admin account to access the Django admin panel.
    ```bash
    python manage.py createsuperuser
    ```

7.  **Run the Development Server**
    *   Make sure you are in the directory containing `manage.py`.
    ```bash
    python manage.py runserver
    ```
    The website will be running at `http://127.0.0.1:8000/`.

8.  **How the Movie Data Was Imported**

    **Note**: The following steps are for documentation only. The provided database is already populated.

    1. The `fetch_tmdb_movies.ipynb` notebook was run to download posters and create the `tmdb_movies.json` file.
    2. The downloaded posters were moved from their initial location to the `media/posters/` directory.
    3. A tool like Postman was used to make a `POST` request to the `/api/import_tmdb_movies/` endpoint.
        *   Authentication was done using the admin superuser credentials.
        *   The request body contained the `tmdb_movies.json` data.
    4. The data was verified via the **/admin** panel.

## Phase 2 – AWS Integration (ECR, EC2, RDS, S3, Bedrock)

This section documents how the same codebase runs locally and on AWS, in the order we recommend building it.

### 1) Prep (env + project)
- Two env files (not committed): `.env.dev` (local), `.env.prod` (EC2). Load via `DEPLOY_ENV` and `dotenv.load_dotenv(BASE_DIR / f".env.{DEPLOY_ENV}")`.
- Keep `DEBUG=True` per course; `ALLOWED_HOSTS=["*"]` is acceptable.
- Dockerfile (Daphne) and `.dockerignore` at repo root; static served by Django with `staticfiles_urlpatterns()`.

### 2) IAM (instance role + Bedrock access)
- EC2 role: allow S3 read/write on your media bucket, ECR pull, and `bedrock:InvokeModel` (and `InvokeModelWithResponseStream` if needed).
- Bedrock console: enable access to your chosen model (e.g., Haiku or Sonnet).

### 3) ECR (build/push image)
- Build/push (replace account/region):
  ```bash
  docker build --pull --no-cache -t mymdb:prod .
  docker tag mymdb:prod <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/mymdb-repo:prod
  aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com
  docker push <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/mymdb-repo:prod
  ```

### 4) RDS (PostgreSQL)
- In prod: `ENGINE=django.db.backends.postgresql` (dev stays SQLite).
- Security Groups: RDS inbound `5432` from the EC2 instance SG.
- Console steps (quick):
  - Create database → Engine: PostgreSQL → Templates: Free tier.
  - DB instance identifier: choose a name; Master username/password.
  - Storage: gp3 (default is fine for demo).
  - Connectivity: Public access = Yes; Do not connect to an EC2 compute resource.
  - Create DB and note the Endpoint (hostname) for `.env.prod`.

### 5) S3 (media only)
- `django-storages` default storage to S3 (location `media`, `default_acl: public-read` or a public bucket policy). 
- `MEDIA_URL` points to your bucket domain (avoid `/media/media/`).
- Console steps (quick):
  - Create bucket → General purpose → Bucket name.
  - ACLs: Enabled; Block public access: uncheck all (for demo).
  - Upload posters from repo path: `mymdb/mymdb/media/posters/` (keys will be under `media/posters/...`).

### 6) EC2 (single instance run)
- Launch an Ubuntu instance with the IAM role; open inbound TCP `8000` for testing.
- Connect to the instance using EC2 Instance Connect or SSH
- Set and Copy the local `.env.prod` to the instance's location`/home/ubuntu/mymdb/.env.prod`.
- Install Docker and AWS CLI
  `https://docs.docker.com/engine/install/ubuntu/`
  `https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html`

- Allow docker command without sudo:
  ```bash
  sudo usermod -aG docker $USER
  newgrp docker
  ```

- Login to ECR and pull the image:
  ```bash
  aws ecr get-login-password --region <REGION> \
  | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com
  docker pull <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/mymdb-repo:prod
  ```
- Run container:
  ```bash
  docker run -d --name mymdb-instance-01 \
    -p 8000:8000 --restart unless-stopped \
    --env-file /home/ubuntu/mymdb/.env.prod \
    -w /app/mymdb \
    <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/mymdb-repo:prod
  ```
- Enter the container and Run migrations and create admin inside the container:
  ```bash
  docker exec -it mymdb-instance-01 bash
  python manage.py migrate
  python manage.py createsuperuser
  
  ```

### 7) Import data on EC2
- `POST /api/import_tmdb_movies/` (admin auth). Accepts raw JSON or `file` upload.
- Poster keys like `posters/xyz.jpg` resolve against S3 in prod.

### 8) Bedrock test and tuning
- Env: `AI_PROVIDER=bedrock`, `AWS_REGION`, `BEDROCK_MODEL_ID` (no quotes).
- If throttled or non-JSON text: use Haiku, lower `max_tokens`, set `temperature=0`, and rely on JSON fallback in code.

- Note: Bedrock returns plain text (not valid JSON) for the conversational step, so our JSON parse failed and the fallback kicked in. To reduce this:
  - Tighten the conversational system instruction to “return ONLY a JSON object { "text": "..." }”.
  - Set temperature=0 in the Bedrock call to make it stick to “JSON only”.
  - Improve fallback: if JSON parse fails, use the model’s text as the message and still attach your DB links, not the generic line.


### 9) Target Group & Load Balancer 
- Create Target Group (Instances, name it, HTTP 80, health path `/`, register the two instances to port 8000).
- Create ALB (listener 80) → forward to TG; restrict EC2 SG to ALB SG.

## Phase 3 – Realtime Multi‑User Chat (Channels + Kafka + React)

### Architecture
- WebSockets: Django Channels (Daphne) with `AuthMiddlewareStack` (login required).
- Kafka in the loop:
  - Producer: WS consumer publishes chat events to topic (`chat-messages`, key = room slug).
  - Broadcaster: a background Kafka consumer embedded in the ASGI process rebroadcasts to the local Channels group (works without Redis).
  - Persister: a single management command consumer (`persist_kafka`) writes `Room` and `Message` rows to DB using an idempotent `event_id`.
- React frontend: Vite dev server with proxy ( `/api` and `/ws` → `http://localhost:8000`), rendered inside a small iframe panel launched from `base.html`.

### Data model (new)
- `chat.Room(name, slug, created_by, created_at)` – `slug` is unique.
- `chat.Message(event_id UUID unique, room→FK, user→FK nullable, content, created_at)` – `event_id` guarantees exactly‑once inserts.

### Endpoints
- REST for React:
  - `GET /api/chat/rooms/` – list rooms.
  - `POST /api/chat/rooms/?name=...` – create if missing (auth required).
  - `GET /api/chat/rooms/<slug>/messages?limit=50` – recent history.
- WebSocket: `ws://<host>/ws/chat/<slug>/` (regex allows hyphens: `[-\w]+`).

### Broadcaster: embedded vs external

- We use the embedded broadcaster: `chat/kafka_background.py` starts a Kafka consumer inside the ASGI process (via `chat/apps.py`). It rebroadcasts to Channels groups locally, which works with the in‑memory channel layer (no Redis).
- Do NOT run `python manage.py broadcast_kafka` in normal use. It lives in a separate process and cannot deliver to WebSocket groups with the in‑memory layer. Keep it only for debugging, or if you implement the HTTP relay pattern (external consumer POSTs to a Django endpoint that calls `group_send`).
- Normal dev run: Kafka → Daphne (ASGI) → embedded broadcaster → clients; plus a single `persist_kafka` process to write to DB.

### Local run (dev)
Prereqs: Docker Desktop, Node 18+, Python venv

1) Start Kafka (+ UI)
```bash
docker compose -f kafka-infra/docker-compose.yml up -d
```

2) Start Django (ASGI)
```bash
daphne -b 0.0.0.0 -p 8000 mymdb.asgi:application
```

(Do not run `broadcast_kafka`; broadcaster is embedded in ASGI.)

3) Start DB writer (single process)
```bash
python manage.py persist_kafka
```

4) Start React dev
```bash
cd chat-frontend && npm run dev
```
Open MyMDB and click the blue 💬 bubble to open the chat panel (an iframe to the React app).

### Environment variables
- `BOOTSTRAP_SERVERS=localhost:29092`
- `TOPIC_NAME=chat-messages`
- Embedded broadcaster: optional `GROUP_ID` (leave empty in dev; in K8s set a unique value per pod).
- Persister: `PERSIST_GROUP_ID=chat-db-writer` (single global writer).

### Windows dev note (static MIME types)
If the browser refuses to load `.js`/`.css` as “text/plain”, add in `settings.py`:
```python
import mimetypes
mimetypes.add_type("application/javascript", ".js", True)
mimetypes.add_type("text/javascript", ".js", True)
mimetypes.add_type("text/css", ".css", True)
```

### CSRF/Proxy (React → Django)
- Vite proxy in `vite.config.js` routes `/api` and `/ws` to `http://localhost:8000`.
- `CSRF_TRUSTED_ORIGINS` includes `http://localhost:5173`.
- Frontend sends `X-CSRFToken` on POST to `/api/chat/rooms/` (uses cookie `csrftoken`).

### CHATBOT RAG UPGRADE (FAISS + local embeddings)
- Retrieval: FAISS (RAM-only) built at process start from `Movie` rows. Embeddings via `sentence-transformers` (no API cost).
- Generation: single Gemini call per request; no Gemini embeddings used.
- Intent gate (rule-based): “search”, “more”, “summary”, “off_topic”. OFF-topic/vague shows a clarifying question (no recs). “more” excludes already-shown and inherits prior genres if none specified.
- Filters: genres and year/decade recognized from the user message.

Env (backend):
- `RAG_TOP_K` (default 5): number of candidates to retrieve before filtering/sorting.
- `RAG_MAX_DOCS` (default 500): cap movies embedded at startup.
- `RAG_MIN_SIM` (default 0.25): min cosine similarity to accept RAG results; below → no recs (clarify instead).
- `RAG_EMBED_MODEL` (default `all-MiniLM-L6-v2`).

Local deps:
- `faiss-cpu`, `numpy`, `sentence-transformers` (installed in venv; listed in requirements).

Troubleshooting:
- If the first request is slow in a new pod: that’s the one-time model download + FAISS build.
- If responses feel too eager: increase `RAG_MIN_SIM` (e.g., 0.35–0.45).
- If variety is low: raise `RAG_TOP_K` (e.g., 10–15).

### Scaling to K8s (preview)
- Backend: 3 replicas; each pod runs the embedded broadcaster with a unique `GROUP_ID` so every pod receives every message and fans out to its own sockets (no Redis needed per course scope).
- Persister: 1 replica deployment with `PERSIST_GROUP_ID=chat-db-writer`.
- React: single deployment/service; expose via Ingress/LoadBalancer. Kafka can run in‑cluster or externally.

K8s changes after RAG upgrade:
- No new services or components. Only add envs to the backend Deployment:
  - `RAG_TOP_K`, `RAG_MAX_DOCS`, `RAG_MIN_SIM`, `RAG_EMBED_MODEL`.

# Appendix
## Key choices (to stay within course scope)

* **Function-Based Views** (not CBVs), per instruction.
* **Essential fields only** (no full TMDB clone).
* **No serializers** for this admin-only import to keep it simple (validation handled inline).
* **No external IDs** in the DB (kept in JSON only).
* **Four main actors** enforced during import (exercise requirement).
* Posters handled as files in `media/posters/` (not uploaded via API).
* **Jupyter notebook for data collection**: I could have created a Django management command to fetch data from TMDB and import directly to the database, but since we haven't covered management commands in class yet, I went with the Jupyter notebook approach to collect the data first, then import via API.
* **Separate `accounts` app**: While the current authentication features could live inside the main project, creating a dedicated `accounts` app is a forward-thinking choice. I may want to add a user profile model with additional fields.
* **Project Naming**: I recognize that having the repository, the Django project, and the main settings application all named `mymdb` is a bit confusing. This was an unintentional result of the initial setup. I plan to fix it and in future projects, I'll use more distinct naming (e.g., `core` or `config` for the settings app, backend or server for the back) to improve clarity.


## Notes and Future Improvements
Things i am thinkging about or haven't got to them yet:

* **Data Fetching**: The Jupyter notebook could be replaced with a more integrated Django management command to fetch a wider range of movie data and handle poster downloads automatically.
* **AI Chatbot**: Missing streaming for the chatbot's responses and more tunings and tweakings are needed for the conversational instructions.
* **AI Integration**: The current two-step AI intent parsing could be upgraded to use Gemini's native function calling for more reliable and extensible movie searches.
* **UI/UX**: Minor user interface and experience enhancements can be implemented to improve navigation and usability.
* **Project Structure**: The current project layout, with the `venv` and `requirements.txt` in the root `MyMDB` directory, is a result of the initial PyCharm setup. A future refactor could involve moving these into the `mymdb` backend directory and restructuring the root to accommodate a separate `frontend` application, creating a more conventional monorepo structure.
---
Thank you for reviewing my project.