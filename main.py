
import asyncio

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
import os
import requests
from dotenv import load_dotenv

from services.datalab import convert_documents

load_dotenv()

app = FastAPI()




@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    file_location = f"temp/{file.filename}"
    
    result = await convert_documents(file_location)
    return {"result": result}
    

@app.post("/webhook/datalab")
async def datalab_webhook(request: Request):
    data = await request.json()
    
    expected_secret = os.getenv("DATALAB_WEBHOOK_SECRET")
    received_secret = data.get("webhook_secret")

    if received_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    request_id = data["request_id"]
    check_url = data["request_check_url"]
    
    response = requests.get(
        check_url,
        headers={"X-API-Key": os.getenv("DATALAB_API_KEY")}
    )

    result_data = response.json()

    print("Processed Result:", result_data)

    return {"status": "received"}