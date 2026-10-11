# Deployment notes

The repository does not deploy automatically, but it is ready for deployment. Build the React client with `npm --prefix frontend run build`; a production web server can serve `frontend/dist`, forwarding `/api` to FastAPI. Alternatively use FastAPI static-file hosting after copying the build directory.

For an Ubuntu EC2 deployment, create a virtual environment, run `pip install -r requirements.txt`, build the React client, secure `.env` with `chmod 600 .env`, and run FastAPI with `uvicorn main:app --host 127.0.0.1 --port 8000`. Use systemd, Nginx, a non-root service account, and TLS for production. Health checks use `/health`.

Set `OPENAI_API_KEY` (and, when required, `OPENAI_BASE_URL`) for OpenAI/proxy usage. If that is empty, set `GEMINI_API_KEY` for Gemini. Secrets are never returned by the API or committed to source control.

