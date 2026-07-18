from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    postgres_dsn: str = "postgresql+psycopg2://agent:agent@localhost:5432/agent_runtime"
    redis_url: str = "redis://localhost:6379/0"
    max_iterations: int = 10
    llm_timeout_seconds: int = 60
    tool_timeout_seconds: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
