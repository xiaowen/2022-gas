import io
import os
from PIL import Image

from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient

from google.api_core.client_options import ClientOptions
import google.auth
from google.cloud import documentai
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Spreadsheet constants
SPREADSHEET_ID = '1iiFiRZQ-UAY5y78g6YN6yD-MJB0lJZ0wqOLZIlw4-z0'
SHEET_NAME_AZURE = 'Azure'
SHEET_NAME_GCLOUD = 'GCloud'
SHEET_NAME_GCLOUD_CUSTOM = 'GCloud-custom'

# Google Cloud and Doc AI constants
GCLOUD_PROJECT_ID = 'tensile-howl-307302'
DOCAI_LOCATION = 'us'
DOCAI_PROCESSOR_ID = 'be5c4fa46ae54842'
DOCAI_CUSTOM_PROCESSOR_ID = 'e03f472481e331e4'

# Azure constants
AZURE_FORM_RECOGNIZER_ENDPOINT = "https://xiaowenx.cognitiveservices.azure.com/"
AZURE_FORM_RECOGNIZER_KEY = os.environ['AZURE_COGNITIVE_SERVICES_KEY']


def get_sheets_data(sheet_name):
    # Get data from the spreadsheet
    sheet = build('sheets', 'v4').spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=sheet_name+"!A2:D").execute()
    values = result.get('values', [])

    # Reformat to a dictionary with file names as keys
    return dict( (x[0], [i] + x[1:]) for i, x in enumerate(values) )

def append_to_sheet(sheet_name, file_name, image_date, price_per_gal, note):
    sheet = build('sheets', 'v4').spreadsheets()
    return sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=sheet_name+"!A2:D",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={ 'values': [[file_name, image_date, price_per_gal, note]]}).execute()

def parse_receipt_gcloud_custom(image_content):
    opts = ClientOptions(api_endpoint=f"{DOCAI_LOCATION}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)
    name = client.processor_path(GCLOUD_PROJECT_ID, DOCAI_LOCATION, DOCAI_CUSTOM_PROCESSOR_ID)

    raw_document = documentai.RawDocument(content=image_content, mime_type='image/jpeg')
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    result = client.process_document(request=request)
    document = result.document

    ents = dict((e.type_, e.text_anchor.content) for e in document.entities)

    price_per_gal = ents.get('price-per-gal', '')
    price_per_gal = price_per_gal and price_per_gal.split()[-1]
    note = 'Parsed: %s' % (ents)

    return price_per_gal, note

def parse_receipt_gcloud(image_content):
    opts = ClientOptions(api_endpoint=f"{DOCAI_LOCATION}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)
    name = client.processor_path(GCLOUD_PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID)

    raw_document = documentai.RawDocument(content=image_content, mime_type='image/jpeg')
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    result = client.process_document(request=request)
    document = result.document

    price_per_gal, note = None, ''

    # Try parsing data from key/value pairs
    for field in document.pages[0].form_fields:
        field_name = field.field_name.text_anchor.content.strip()
        field_value = field.field_value.text_anchor.content.strip()

        if field_name.upper().startswith('PRICE/G'):
            note += "Parsed from form fields: '%s' ; '%s' ; " % (field_name, field_value)
            price_per_gal = field_value

            break

    # Try parsing data from tables
    for table in document.pages[0].tables:
        for row in table.body_rows:
            row_texts = []
            for cell in row.cells:
                if not cell.layout.text_anchor:
                    row_texts.append('')
                    continue

                for segment in cell.layout.text_anchor.text_segments:
                    row_texts.append(document.text[segment.start_index:segment.end_index])

            row_text = ''.join(row_texts)
            if row_text.upper().startswith('PRICE/G'):
                note += "Parsed from table: '%s' ; " % (row_texts)
                price_per_gal = price_per_gal or row_text.split()[1]

                break

    # Try parsing data from raw OCR text
    lines = document.text.split('\n')
    for idx, line in enumerate(lines):
        if line.startswith('PRICE/G'):
            if len(line.split()) >= 2:
                price_per_gal = price_per_gal or line.split()[1]
                note += "Parsed from OCR: '%s' ; " % (line)
                break
            else:
                price_per_gal = price_per_gal or lines[idx+1]
                note += "Parsed from OCR: '%s', '%s' ; " % (line, lines[idx+1])
                break

    return price_per_gal, note

def parse_receipt_azure(image_content):
    document_analysis_client = DocumentAnalysisClient(
        endpoint=AZURE_FORM_RECOGNIZER_ENDPOINT,
        credential=AzureKeyCredential(AZURE_FORM_RECOGNIZER_KEY))

    poller = document_analysis_client.begin_analyze_document("prebuilt-document", document=image_content)
    result = poller.result()

    price_per_gal, note = None, ''

    # Try to find the info we need in the key/value pairs
    for kv_pair in result.key_value_pairs:
        if kv_pair.key and kv_pair.value:
            if kv_pair.key.content.startswith('PRICE/G'):
                price_per_gal = kv_pair.value.content
                note += "KV pairs key '{}': value: '{}' ; ".format(kv_pair.key.content, kv_pair.value.content)

                break

    return price_per_gal, note

if __name__ == "__main__":
    # Get the list of images from disk
    files = os.listdir('photos')

    for cloud in ['gcloud', 'gcloud_custom', 'azure']:
        print('Working on: ' + cloud)

        # Get the existing info in the spreadsheet
        sheet_name = dict(
            gcloud=SHEET_NAME_GCLOUD,
            gcloud_custom=SHEET_NAME_GCLOUD_CUSTOM,
            azure=SHEET_NAME_AZURE)[cloud]
        sheets_data = get_sheets_data(sheet_name)

        for file_name in files:
            if not file_name.endswith('.jpg'):
                continue

            if file_name in sheets_data:
                continue # Skip if this file has already been processed

            # Read the image from disk
            with open('photos/' + file_name, "rb") as image:
                image_content = image.read()

            # Get the date of the image from the EXIF data
            image_date = Image.open(io.BytesIO(image_content))._getexif()[36867]
            image_date = image_date.replace(':', '/', 2) # It likes to format dates as YYYY:MM:DD for some reason

            print('Processing: %s, image date: %s' % (file_name, image_date))

            # Parse the image
            if cloud == 'gcloud':
                price_per_gal, note = parse_receipt_gcloud(image_content)
            elif cloud == 'gcloud_custom':
                price_per_gal, note = parse_receipt_gcloud_custom(image_content)
            elif cloud == 'azure':
                price_per_gal, note = parse_receipt_azure(image_content)

            # Add results to spreadsheet
            append_to_sheet(sheet_name, file_name, image_date, price_per_gal, note)