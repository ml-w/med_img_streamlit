import os
import sys
import logging
import click
import streamlit.web.bootstrap
from streamlit import logger
from rich.logging import RichHandler


# --- Rich logging injection ---

def setup_formatter(log: logging.Logger) -> None:
    """Set up the Rich console formatter for a given logger."""
    for hdlr in log.handlers:
        log.removeHandler(hdlr)
    log.streamlit_console_handler = RichHandler(rich_tracebacks=True, tracebacks_show_locals=True)  # type: ignore[attr-defined]

    from streamlit import config
    if config._config_options:
        message_format = config.get_option("logger.messageFormat")
    else:
        message_format = None

    formatter = logging.Formatter(fmt=message_format)
    formatter.default_msec_format = "%s.%03d"
    log.streamlit_console_handler.setFormatter(formatter)  # type: ignore[attr-defined]
    log.addHandler(log.streamlit_console_handler)  # type: ignore[attr-defined]


logger.setup_formatter = setup_formatter

_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "application")


def _running_in_streamlit() -> bool:
    """True when the script is executed by ``streamlit run``."""
    try:
        from streamlit.runtime import exists
        return exists()
    except Exception:
        return False


if _running_in_streamlit():
    # Launched via `streamlit run run_app.py` — runtime already exists.
    # Change into the application directory so relative imports in user_interface.py resolve.
    os.chdir(_APP_DIR)
    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)
    from user_interface import streamlit_app  # type: ignore[import]
    streamlit_app()


@click.command()
@click.option("--port", default=8501, show_default=True, help="Server port.")
@click.option(
    "--log-level", "log_level", default="DEBUG", show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level.",
)
def main(port: int, log_level: str) -> None:
    """Launch the DICOM Anonymizer Streamlit app."""
    st_logger = logger.get_logger("anonymizer")
    logger.set_log_level(log_level)
    st_logger.info("Initiating DicomAnonymizer")
    st_logger.info(" - log level = {}".format(log_level))
    st_logger.debug(" - Confirm debug log level")
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    flag_options = {
        "server.port": port,
        "global.developmentMode": False,
    }
    streamlit.web.bootstrap.load_config_options(flag_options=flag_options)
    flag_options["_is_running_with_streamlit"] = True
    streamlit.web.bootstrap.run(
        "./application/DicomAnonymizer.py",
        False,
        [],
        flag_options,
    )


if __name__ == "__main__":
    main()
