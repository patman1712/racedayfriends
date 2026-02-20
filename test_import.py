import traceback
try:
    import iracingdataapi
    from iracingdataapi.client import irDataClient
    print("Import successful!")
except Exception:
    traceback.print_exc()
