from datetime import date

import redis
from fastapi import HTTPException, status

from app.core.config import settings


class RateLimiter:
    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def _handle_error(self, exc: redis.RedisError) -> None:
        if settings.environment == "production":
            raise HTTPException(status_code=503, detail="访问控制服务暂时不可用") from exc

    def check(self, session_hash: str) -> None:
        today = date.today().isoformat()
        hour_key = f"rate:hour:{today}:{session_hash}"
        daily_key = f"budget:requests:{today}"
        token_key = f"budget:tokens:{today}"
        try:
            pipeline = self.client.pipeline()
            pipeline.incr(hour_key)
            pipeline.expire(hour_key, 3700)
            pipeline.incr(daily_key)
            pipeline.expire(daily_key, 172800)
            pipeline.get(token_key)
            hourly, _, daily, _, tokens = pipeline.execute()
            if int(hourly) > settings.guest_requests_per_hour:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="本小时提问次数已用完")
            if int(daily) > settings.global_requests_per_day:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="今日问答额度已用完")
            if int(tokens or 0) >= settings.global_tokens_per_day:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="今日模型预算已用完")
        except redis.RedisError as exc:
            self._handle_error(exc)

    def add_tokens(self, count: int) -> None:
        if count <= 0:
            return
        key = f"budget:tokens:{date.today().isoformat()}"
        try:
            pipeline = self.client.pipeline()
            pipeline.incrby(key, count)
            pipeline.expire(key, 172800)
            pipeline.execute()
        except redis.RedisError as exc:
            self._handle_error(exc)


rate_limiter = RateLimiter()

