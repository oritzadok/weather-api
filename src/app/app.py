import time
import json
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic_settings import BaseSettings
import httpx
import aioboto3
from botocore.exceptions import ClientError


# --- Configuration Management ---
class Settings(BaseSettings):
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str
    DYNAMODB_TABLE_NAME: str
    OPENWEATHER_API_KEY: str
    OPENWEATHER_BASE_URL: str = "https://api.openweathermap.org/data/2.5/weather"

    class Config:
        env_file = ".env"


settings = Settings()


# --- Global HTTP Client Management ---
# We use a lifespan context manager to reuse a single HTTP client
# rather than opening a new connection for every request.
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient()
    yield
    await app.state.http_client.aclose()


app = FastAPI(lifespan=lifespan)


# --- Helper Services ---

async def fetch_weather(city: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """Asynchronously fetches weather data from external API."""
    params = {
        "q": city,
        "appid": settings.OPENWEATHER_API_KEY,
        "units": "metric"
    }
    response = await client.get(settings.OPENWEATHER_BASE_URL, params=params)
    
    if response.status_code != 200:
        # Pass through the external API error
        raise HTTPException(status_code=response.status_code, detail="Weather service unavailable or city not found")
    
    return response.json()


async def upload_to_s3(session: aioboto3.Session, data: dict, filename: str) -> str:
    """Uploads JSON to S3 and returns the S3 URL."""
    try:
        json_bytes = json.dumps(data).encode('utf-8')
        
        async with session.client("s3", region_name=settings.AWS_REGION) as s3:
            await s3.put_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=filename,
                Body=json_bytes,
                ContentType="application/json"
            )
            
        return f"s3://{settings.S3_BUCKET_NAME}/{filename}"
    except ClientError as e:
        print(f"S3 Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload weather data")


async def log_to_dynamodb(session: aioboto3.Session, city: str, timestamp: int, s3_url: str):
    """Logs the event metadata to DynamoDB."""
    try:
        item = {
            "city": city,                 # Partition Key
            "timestamp": timestamp,       # Sort Key (optional, but recommended)
            "s3_url": s3_url,
            "processed_at": str(time.time())
        }
        
        async with session.resource("dynamodb", region_name=settings.AWS_REGION) as dynamo_resource:
            table = await dynamo_resource.Table(settings.DYNAMODB_TABLE_NAME)
            await table.put_item(Item=item)
            
    except ClientError as e:
        print(f"DynamoDB Error: {e}")
        # We might not want to fail the user request if logging fails, 
        # but for this example, we will raise an error.
        raise HTTPException(status_code=500, detail="Failed to log transaction")


# --- The Endpoint ---

@app.get("/weather")
async def get_weather(city: str = Query(..., min_length=1)):
    timestamp = int(time.time())
    filename = f"{city}_{timestamp}.json"
    
    # 1. Fetch Weather (Non-blocking I/O)
    weather_data = await fetch_weather(city, app.state.http_client)
    
    # Initialize AWS Session
    session = aioboto3.Session()
    
    # 2. Upload to S3
    s3_url = await upload_to_s3(session, weather_data, filename)
    
    # 3. Log to DynamoDB
    # Note: If high performance is critical, you could fire this as a background task
    # using BackgroundTasks so the user gets a response faster.
    await log_to_dynamodb(session, city, timestamp, s3_url)
    
    return {
        "city": city,
        "temperature": weather_data.get("main", {}).get("temp"),
        "status": "success"
    }