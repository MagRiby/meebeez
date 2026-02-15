import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Ensure the platform directory is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from core import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
