"""
Módulo de Rate Limiting y Protección contra Fuerza Bruta (DNI / PIN / Login / OTP).
Mitiga ataques de enumeración de DNIs y adivinación de PIN de 4 dígitos en el Portal de Dueños.
"""
import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    def __init__(self):
        # key -> list of timestamps
        self._hits: Dict[str, List[float]] = defaultdict(list)
        # identifier (ej. dni) -> (failed_count, lock_until_timestamp)
        self._lockouts: Dict[str, Tuple[int, float]] = {}

    def clear_all(self) -> None:
        """Limpia contadores (útil en suites de pruebas)."""
        self._hits.clear()
        self._lockouts.clear()

    def get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    def check_rate_limit(
        self,
        key_or_request,
        max_requests: int = 10,
        window_seconds: int = 60,
        scope: str = "default"
    ) -> None:
        if isinstance(key_or_request, str):
            key = key_or_request
        else:
            ip = self.get_client_ip(key_or_request)
            key = f"{scope}:{ip}"

        now = time.time()
        cutoff = now - window_seconds
        hits = [t for t in self._hits[key] if t > cutoff]
        if len(hits) >= max_requests:
            self._hits[key] = hits
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes. Por seguridad, espera un minuto antes de volver a intentarlo."
            )
        hits.append(now)
        self._hits[key] = hits

    def check_pin_lockout(self, dni: str) -> None:
        now = time.time()
        info = self._lockouts.get(dni)
        if info:
            fails, lock_until = info
            if lock_until > now:
                segundos_restantes = int(lock_until - now)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Cuenta bloqueada temporalmente por múltiples intentos fallidos de PIN. Intenta nuevamente en {segundos_restantes} segundos."
                )
            elif lock_until != 0 and lock_until <= now:
                # Expiró el bloqueo
                del self._lockouts[dni]

    def record_pin_failure(self, dni: str, max_attempts: int = 5, lockout_seconds: int = 900) -> None:
        now = time.time()
        fails, lock_until = self._lockouts.get(dni, (0, 0.0))
        if lock_until > 0 and lock_until <= now:
            fails = 0
        fails += 1
        if fails >= max_attempts:
            self._lockouts[dni] = (fails, now + lockout_seconds)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Has superado el límite de 5 intentos fallidos de PIN. Tu acceso ha sido bloqueado por 15 minutos por seguridad."
            )
        self._lockouts[dni] = (fails, 0.0)

    def reset_pin_failures(self, dni: str) -> None:
        self._lockouts.pop(dni, None)


rate_limiter = SlidingWindowRateLimiter()
