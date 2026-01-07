from fastapi import FastAPI

app = FastAPI()

@app.get("/weather/")
async def get_weather(city: str):
    return {"Hello": city}