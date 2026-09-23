import os
import requests

JEV_API_URL = "https://api.typesafe.ai/v1/systemone"
JEV_API_KEY = os.environ.get("TYPESAFE_API_KEY")

if not JEV_API_KEY:
    raise RuntimeError("TYPESAFE_API_KEY is not set")

def call_jev(state: dict, questions: dict) -> dict:
    payload = {
        "model": "jev-latest",
        "state": state,
        "questions": questions,
    }
    resp = requests.post(
        JEV_API_URL,
        headers={
            "Authorization": f"Bearer {JEV_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
