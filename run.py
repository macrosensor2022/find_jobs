#!/usr/bin/env python
"""
JobTracker — OPT Full-Time Job Command Center
Run this script to start the application.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    from backend import scheduler
    from backend.app import app
    from config.settings import Config

    port = Config.PORT
    print("\n" + "=" * 60)
    print("  JobTracker — Personal Job-Search Command Center")
    print("=" * 60)
    print("\n  Starting server...")
    print(f"  Open http://localhost:{port} in your browser")

    handle = scheduler.start(app)
    if handle is not None:
        print(
            f"  Daily search scheduled for "
            f"{Config.SCHEDULE_HOUR:02d}:{Config.SCHEDULE_MINUTE:02d} "
            f"{Config.SCHEDULE_TIMEZONE}"
        )
    else:
        print("  Daily search scheduler is disabled")

    print("\n  Press Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    try:
        app.run(debug=False, port=port, host='0.0.0.0', threaded=True)
    finally:
        scheduler.stop()


if __name__ == '__main__':
    main()
