# Campus AutoGTM

Campus AutoGTM is an agentic GTM engine for education and training providers. It discovers colleges,
enriches contacts, scores fit using Jev (TypeSafe System One model), and routes qualified opportunities
into a CRM + operations hub.

## Quick start

1. Create a Python virtualenv and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy env example and set your Jev API key:

   ```bash
   cp infra/env.example .env
   # edit .env to set TYPESAFE_API_KEY
   ```

3. Run the FastAPI app:

   ```bash
   uvicorn app.main:app --reload
   ```

4. Create a campaign via `POST /campaigns`, then run it via `POST /campaigns/{id}/run` and inspect
   discovered leads at `GET /leads`.
