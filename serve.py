import os
from waitress import serve
from app import create_app

if __name__ == "__main__":
    serve(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threads=4,
          max_request_body_size=4096, channel_timeout=120)
