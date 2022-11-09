# 2022-gas

The main code is in `main.py`.  To run it, configure the environment as follows:
1. (Optional) set up Python [venv](https://docs.python.org/3/library/venv.html).
2. Install Python libraries: `pip3 install google-api-python-client google-auth-httplib2 google-auth-oauthlib google-cloud-documentai azure azure-ai-formrecognizer Pillow`
3. Configure the environment to use a Google Cloud service account.  If using a key file, then set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable.
4. Put your Azure API key into the `AZURE_COGNITIVE_SERVICES_KEY` enviroment variable.