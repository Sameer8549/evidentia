from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    evidentia_host: str = "127.0.0.1"
    evidentia_port: int = 8000
    evidentia_ollama_url: str = "http://127.0.0.1:11434"
    evidentia_ollama_model: str = "gemma4:e4b"
    evidentia_data_dir: str = ".local"
    evidentia_max_upload_mb: int = 20
    evidentia_max_pages: int = 20
    evidentia_max_image_dim: int = 8000
    evidentia_max_image_pixels: int = 40000000
    evidentia_tesseract_cmd: str = "tesseract"
    evidentia_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
