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


# Configuration Management
class Settings(BaseSettings):
    S3_BUCKET_NAME: str
    DYNAMODB_TABLE_NAME: str
    OPENWEATHER_API_KEY: str
    OPENWEATHER_BASE_URL: str = "https://api.openweathermap.org/data/2.5/weather"

    class Config:
        env_file = ".env"

settings = Settings()


# Global HTTP Client Management
# We use a lifespan context manager to reuse a single HTTP client
# rather than opening a new connection for every request
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient()
    yield
    await app.state.http_client.aclose()


app = FastAPI(lifespan=lifespan)


async def fetch_weather(city: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """Asynchronously fetches weather data from external API"""
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


CACHE_TTL_SECONDS = 300

# list_objects_v2 is O(N). S3 LIST calls cost money, DynamoDB-based cache index is cheaper at scale.
# Better long-term solution:
# - Store latest cache pointer in DynamoDB.
# - Or use a fixed key: cache/{city}.json + metadata.
# Can also add Cache-Control metadata on S3 objects, or use S3 Object Tags (cached_at)
async def get_cached_weather(
    session: aioboto3.Session,
    city: str,
    now_ts: int
) -> Dict[str, Any] | None:
    """
    Returns cached weather data if exists and not expired, otherwise None
    """
    try:
        prefix = f"{city}_"

        async with session.client("s3") as s3:
            response = await s3.list_objects_v2(
                Bucket=settings.S3_BUCKET_NAME,
                Prefix=prefix
            )

            if "Contents" not in response:
                return None

            latest_obj = None
            latest_ts = 0

            for obj in response["Contents"]:
                key = obj["Key"]
                try:
                    ts = int(key.replace(prefix, "").replace(".json", ""))
                    if ts > latest_ts:
                        latest_ts = ts
                        latest_obj = key
                except ValueError:
                    continue

            if not latest_obj:
                return None

            if now_ts - latest_ts > CACHE_TTL_SECONDS:
                return None

            cached_obj = await s3.get_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=latest_obj
            )
            body = await cached_obj["Body"].read()
            return json.loads(body)
    except ClientError as e:
        print(f"S3 Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get cached weather data")


async def upload_to_s3(session: aioboto3.Session, data: dict, filename: str) -> str:
    """Uploads JSON to S3 and returns the S3 URI"""
    try:
        json_bytes = json.dumps(data).encode('utf-8')
        
        async with session.client("s3") as s3:
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


async def log_to_dynamodb(session: aioboto3.Session, city: str, timestamp: int, s3_uri: str):
    """Logs the event metadata to DynamoDB"""
    try:
        item = {
            "city": city,
            "timestamp": timestamp,
            "s3_uri": s3_uri,
            "processed_at": str(time.time())
        }
        
        async with session.resource("dynamodb") as dynamo_resource:
            table = await dynamo_resource.Table(settings.DYNAMODB_TABLE_NAME)
            await table.put_item(Item=item)
            
    except ClientError as e:
        print(f"DynamoDB Error: {e}")
        # We might not want to fail the user request if logging fails, 
        # but for this example, we will raise an error
        raise HTTPException(status_code=500, detail="Failed to log transaction")


@app.get("/weather/")
async def get_weather(city: str = Query(..., min_length=1)):
    timestamp = int(time.time())

    session = aioboto3.Session()

    cached_weather = await get_cached_weather(session, city, timestamp)
    if cached_weather:
        return {
            "city": city,
            "temperature": cached_weather["main"]["temp"],
            "source": "cache"
        }
    
    weather_data = await fetch_weather(city, app.state.http_client)
    
    filename = f"{city}_{timestamp}.json"
    s3_uri = await upload_to_s3(session, weather_data, filename)
    
    # Note: If high performance is critical, can fire this as a background task
    # using BackgroundTasks so the user gets a response faster
    await log_to_dynamodb(session, city, timestamp, s3_uri)
    
    return {
        "city": city,
        "temperature": weather_data["main"]["temp"],
        "source": "api"
    }