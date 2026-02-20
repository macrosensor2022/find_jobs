#!/usr/bin/env python
"""
Job Search Dashboard - Summer 2026 Co-op/Internship Tracker
Run this script to start the application.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    from backend.app import app
    
    print("\n" + "="*60)
    print("  Job Search Dashboard - Summer 2026 Co-op Search")
    print("="*60)
    print("\n  Starting server...")
    print("  Open http://localhost:8080 in your browser")
    print("\n  Press Ctrl+C to stop the server")
    print("="*60 + "\n")
    
    app.run(debug=False, port=8080, host='127.0.0.1', threaded=True)


if __name__ == '__main__':
    main()
