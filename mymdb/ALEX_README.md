# MyMDB

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
  * Assigns posters by **relative path** if the file exists under `MEDIA_ROOT/posters/`.
* **Result of my import run**

  * Created **119** movies, **19** genres, **112** directors, **422** actors.

* **AI Chatbot (Gemini)**

  * **Backend**:
    * A view `chatbot_api` that receives user messages and chat history.
    * It calls `ai_service.get_chatbot_response` which communicates with the Gemini API.
    * The AI service uses function calling to suggest movies from the database based on user queries (e.g., "recommend a comedy").
  * **Frontend**:
    * A chat widget in `base.html`.
    * `static/js/chat.js` handles the communication with the `chatbot_api` endpoint.
    * Displays AI responses and movie recommendations with links to the movie details page.

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
* **AI Chatbot**: More tunings and tweakings are needed for the conversational instructions.
* **AI Integration**: The current two-step AI intent parsing could be upgraded to use Gemini's native function calling for more reliable and extensible movie searches.
* **UI/UX**: Minor user interface and experience enhancements can be implemented to improve navigation and usability.
* **Project Structure**: The current project layout, with the `venv` and `requirements.txt` in the root `MyMDB` directory, is a result of the initial PyCharm setup. A future refactor could involve moving these into the `mymdb` backend directory and restructuring the root to accommodate a separate `frontend` application, creating a more conventional monorepo structure.

## Setup Instructions

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/yanivraveh/mymdb
    cd mymdb/mymdb
    ```

2.  **Create and Activate a Virtual Environment**
    *   **For Windows:**
        ```bash
        python -m venv venv
        .\venv\Scripts\activate
        ```
    *   **For macOS/Linux:**
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```

3.  **Install Dependencies**
    ```bash
    pip install -r ../requirements.txt
    ```

4.  **Set Up Environment Variables**
    *   Create a file named `.env` in the `mymdb` directory (the one with `manage.py`).
    *   Add your Gemini API key to this file:
        ```
        GEMINI_API_KEY="your_api_key_here"
        ```

5.  **Run Database Migrations**
    ```bash
    python manage.py migrate
    ```

6.  **Create an Admin Superuser**
    *   You'll need an admin account to access the Django admin panel and use the data import endpoint.
    ```bash
    python manage.py createsuperuser
    ```

7.  **Run the Development Server**
    ```bash
    python manage.py runserver
    ```
    The website will be running at `http://127.0.0.1:8000/`.

8.  **Current Method for Importing Movie Data**
    1. Run the `fetch_tmdb_movies.ipynb` notebook to download posters and create the `tmdb_movies.json` file.
    2. Move the downloaded posters from their initial location to the `media/posters/` directory.
    3. Use a tool like Postman to make a `POST` request to the `/api/import_tmdb_movies/` endpoint.
        *   Use Basic Authentication with the superuser credentials you created.
        *   The request body can be either the raw JSON content of `tmdb_movies.json` or `form-data` with a `file` field pointing to the JSON file.
    4. Verify that the data has been imported correctly by checking the **/admin** panel.

---
Thank you for reviewing my project.

