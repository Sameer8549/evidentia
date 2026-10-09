from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    evidentia_host: str = "127.0.0.1"
    evidentia_port: int = 8000
    evidentia_ollama_url: str = "http://127.0.0.1:11434"
    evidentia_ollama_model: str = "gemma4:e4b"
    evidentia_data_dir: str = ".local"
    evidentia_max_upload_mb: int = 20
    evidentia_max_pages: int = 20

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()

app = FastAPI(
    title="Evidentia",
    description="Make AI show its evidence.",
    version="0.1.0"
)

@app.get("/")
def read_root():
    return {"name": "evidentia-backend", "version": "0.1.0"}
