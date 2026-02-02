import logging
import logging.config
import os
import sys

import asyncio
from config.logging_config import LOGGING_CONFIG
from api.router import Router
from services.satellite_tracker import SatelliteTracker
from contextlib import asynccontextmanager

os.makedirs("logs", exist_ok=True)

logging.config.dictConfig(LOGGING_CONFIG)

# Configure general logger
gs_logger = logging.getLogger("groundstation")
api_logger = logging.getLogger("api")


api_logger.setLevel("DEBUG")



CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
serve_conf_file = os.path.join(CONFIG_DIR, "serve.conf")
tle_script = os.path.join(os.path.dirname(__file__), "../tle_updater.sh")


with open(serve_conf_file, 'r') as file:
    conf = file.read().strip().split(":")
    ip = conf[0]
    port = int(conf[1])


async def main():
    try:
        tracker = await SatelliteTracker.initialize(gs_logger)
        router = Router(api_logger, ip, port, tracker, tle_script)
        await router.connect()
        await router.work()
    except Exception as e:
        gs_logger.critical(e)
        gs_logger.info("shutting down")
        sys.exit(-1)


if __name__ == "__main__":
    # Automatically create the logs folder if not there
    gs_logger.info("Starting server")

    asyncio.run(main())



