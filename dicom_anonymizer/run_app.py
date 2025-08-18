import os
from typing import cast
from streamlit import logger
import logging
import streamlit.web.bootstrap
from rich.logging import RichHandler

# Inject rich handler as formatter
def setup_formatter(logger: logging.Logger) -> None:
    """Set up the console formatter for a given logger."""
    # Deregister any previous console loggers.
    for hdlr in logger.handlers:
        logger.removeHandler(hdlr)
    logger.streamlit_console_handler = RichHandler(rich_tracebacks=True, tracebacks_show_locals=True)  # type: ignore[attr-defined]

    # Import here to avoid circular imports
    from streamlit import config

    if config._config_options:
        # logger is required in ConfigOption.set_value
        # Getting the config option before the config file has been parsed
        # can create an infinite loop
        message_format = config.get_option("logger.messageFormat")
    else:
        message_format = None
        
    formatter = logging.Formatter(fmt=message_format)
    formatter.default_msec_format = "%s.%03d"
    logger.streamlit_console_handler.setFormatter(formatter)  # type: ignore[attr-defined]

    # Register the new console logger.
    logger.addHandler(logger.streamlit_console_handler)  # type: ignore[attr-defined]        
# Inject it
logger.setup_formatter = setup_formatter


if __name__ == "__main__":
    st_logger = logger.get_logger("anonymizer")
    st_logger.info("Initiating DicomAnonymizer")
    logger.set_log_level('DEBUG')
    os.chdir(os.path.dirname(__file__))

    flag_options = {
        "server.port": 8501,
        "global.developmentMode": False,
    }

    streamlit.web.bootstrap.load_config_options(flag_options=flag_options)
    flag_options["_is_running_with_streamlit"] = True
    streamlit.web.bootstrap.run(
        "./application/DicomAnonymizer.py",
        False,
        [],
        flag_options
    )