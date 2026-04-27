import os
import socket
import time

from loguru import logger

port = int(os.environ["DB_PORT"])  # 5432

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Nothing is more permanent than a temporary workaround.
while True:
    try:
        s.connect((os.environ["DB_HOST"], port))
        s.close()
        logger.info("Found database! Leaving.")
        break
    except OSError:
        time.sleep(0.1)
