import os
import streamlit.web.bootstrap

if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))

    flag_options = {
        "server.port": 8501,
        "global.developmentMode": False,
    }

    streamlit.web.bootstrap.load_config_options(flag_options=flag_options)
    flag_options["_is_running_with_streamlit"] = True
    streamlit.web.bootstrap.run(
        "./application/DicomAnonymizer.py",
        "streamlit run",
        [],
        flag_options,
    )