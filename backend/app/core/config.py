from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "HACKALEM AI - Supply Calculation Engine"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./app.db"

    class Config:
        case_sensitive = True

settings = Settings()
