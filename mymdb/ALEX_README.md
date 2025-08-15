# MyMDB

## What’s in my solution

* **Models**

  * `Movie(title, poster, description, director→FK, release_year, main_actors↔M2M, genres↔M2M)`
  * `Director(first_name, last_name)`
  * `Actor(first_name, last_name)`
  * `Genre(name)`
* **Admin**

  * All four models registered in Django Admin for easy add/edit/browse.
* **Data collection (Jupyter Notebook)**

  * Fetches popular movies from TMDB by genre.
  * **Skips adult titles**, **deduplicates** across genres, and **validates poster downloads**.
  * Saves posters locally (manually moved to `media/posters/`) and writes `tmdb_movies.json` with only the fields my app needs.
  * Keeps TMDB IDs **only in the JSON** (for debugging/re-runs); not stored in the DB.
* **Import endpoint (function-based DRF view)**

  * `POST /import_tmdb_movies/` (admin-only via `IsAdminUser`).
  * Accepts either raw JSON or an uploaded JSON file.
  * Upserts movies by `(title, release_year)`.
  * Splits names and creates/links `Director`, creates/links up to **4** `Actor`s, and attaches **all** `Genre`s (M2M).
  * Assigns posters by **relative path** if the file exists under `MEDIA_ROOT/posters/`.
* **Result of my import run**

  * Created **119** movies, **19** genres, **112** directors, **422** actors.

## Key choices (to stay within course scope)

* **Function-Based Views** (not CBVs), per instruction.
* **Essential fields only** (no full TMDB clone).
* **No serializers** for this admin-only import to keep it simple (validation handled inline).
* **No external IDs** in the DB (kept in JSON only).
* **Four main actors** enforced during import (exercise requirement).
* Posters handled as files in `media/posters/` (not uploaded via API).
* **Jupyter notebook for data collection**: I could have created a Django management command to fetch data from TMDB and import directly to the database, but since we haven't covered management commands in class yet, I went with the Jupyter notebook approach to collect the data first, then import via API.


## How I ran the import

1. Ran the notebook to download posters and create `tmdb_movies.json`.
2. Moved posters to `media/posters/`.
3. Used **Postman** (Basic Auth with a staff user) to `POST /import_tmdb_movies/` with:

   * **raw JSON** (paste file contents) **or**
   * **form-data** with a `file` field pointing to `tmdb_movies.json`.
4. Verified data in **/admin** (multi-genre per movie, exactly 4 actors, posters showing).

