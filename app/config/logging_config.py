# API logger config
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "custom": {
            "format": "%(asctime)s - %(levelname)s - %(message)s"
        }
    },
    "handlers": {
        "console": {  # Console handler
            "class": "logging.StreamHandler",
            "formatter": "custom",
            "stream": "ext://sys.stdout",
        },
        "api_file": {  # File handler
            "class": "logging.FileHandler",
            "formatter": "custom",
            "filename": "logs/api.log",
            "mode": "a",  # Append mode
        },
        "gs_file": {  # File handler
            "class": "logging.FileHandler",
            "formatter": "custom",
            "filename": "logs/groundstation.log",
            "mode": "a",  # Append mode
        },
    },
    "loggers": {
        "api": {
            "handlers": ["console", "api_file"],  # Log to both console and file
            "level": "INFO",
            "propagate": False,
        },
        "groundstation":{
            "handlers": ["console", "gs_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
