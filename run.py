import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    public_url = os.environ.get("PUBLIC_BASE_URL", "Not Set")
    print(f"Starting server on port {port}...")
    print(f"PUBLIC_BASE_URL: {public_url}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info")
