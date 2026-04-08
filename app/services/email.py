from __future__ import annotations

import logging
import random
import string
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import EmailConfirmation, ShiftOpenCode

log = logging.getLogger(__name__)

OPERATION_LABELS = {
    "payroll_generate": "Формирование расчётной ведомости",
    "user_create": "Создание пользователя",
    "user_edit_role": "Изменение роли пользователя",
    "user_deactivate": "Деактивация пользователя",
}


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


class EmailService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.smtp_user and self.settings.smtp_password)

    async def send_confirmation_code(
        self,
        db: AsyncSession,
        web_user_id: int,
        admin_email: str,
        operation: str,
        payload_json: str | None = None,
    ) -> str:
        """Generate a code, save it to DB and send to admin_email. Returns the code."""
        # Invalidate previous unused codes for same user+operation
        await db.execute(
            delete(EmailConfirmation).where(
                EmailConfirmation.web_user_id == web_user_id,
                EmailConfirmation.operation == operation,
                EmailConfirmation.used == False,
            )
        )

        code = _generate_code()
        expires_at = datetime.utcnow() + timedelta(minutes=self.settings.email_code_ttl_minutes)

        conf = EmailConfirmation(
            web_user_id=web_user_id,
            operation=operation,
            payload_json=payload_json,
            code=code,
            used=False,
            expires_at=expires_at,
        )
        db.add(conf)
        await db.commit()
        await db.refresh(conf)

        if self.enabled:
            await self._send_email(admin_email, operation, code)
        else:
            log.warning("Email not configured — code for %s: %s", operation, code)

        return code

    async def verify_code(
        self,
        db: AsyncSession,
        web_user_id: int,
        operation: str,
        code: str,
    ) -> tuple[bool, EmailConfirmation | None]:
        """Returns (ok, confirmation_record). Marks code as used if valid."""
        result = await db.execute(
            select(EmailConfirmation).where(
                EmailConfirmation.web_user_id == web_user_id,
                EmailConfirmation.operation == operation,
                EmailConfirmation.used == False,
                EmailConfirmation.code == code,
            )
        )
        conf = result.scalar_one_or_none()
        if not conf:
            return False, None
        if conf.expires_at < datetime.utcnow():
            return False, None

        conf.used = True
        await db.commit()
        return True, conf

    async def send_shift_open_code(
        self,
        db: AsyncSession,
        user_id: int,
        point_id: int,
        shift_date,
        point_email: str,
        point_name: str,
        employee_name: str,
    ) -> str:
        """Generate a 4-digit code, save to DB and send to point_email. Returns the code."""
        from sqlalchemy import delete as sa_delete, and_
        # Invalidate previous unused codes for same user+point+date
        await db.execute(
            sa_delete(ShiftOpenCode).where(
                and_(
                    ShiftOpenCode.user_id == user_id,
                    ShiftOpenCode.point_id == point_id,
                    ShiftOpenCode.shift_date == shift_date,
                    ShiftOpenCode.used == False,
                )
            )
        )

        code = "".join(random.choices(string.digits, k=4))
        expires_at = datetime.utcnow() + timedelta(minutes=10)

        record = ShiftOpenCode(
            user_id=user_id,
            point_id=point_id,
            shift_date=shift_date,
            code=code,
            used=False,
            expires_at=expires_at,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        if self.enabled:
            await self._send_shift_code_email(point_email, point_name, employee_name, code)
        else:
            log.warning("Email not configured — shift code for %s at %s: %s", employee_name, point_name, code)

        return code

    async def verify_shift_open_code(
        self,
        db: AsyncSession,
        user_id: int,
        point_id: int,
        shift_date,
        code: str,
    ) -> bool:
        """Returns True and marks code used if valid, False otherwise."""
        from sqlalchemy import and_
        result = await db.execute(
            select(ShiftOpenCode).where(
                and_(
                    ShiftOpenCode.user_id == user_id,
                    ShiftOpenCode.point_id == point_id,
                    ShiftOpenCode.shift_date == shift_date,
                    ShiftOpenCode.used == False,
                    ShiftOpenCode.code == code,
                )
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return False
        if record.expires_at < datetime.utcnow():
            return False
        record.used = True
        await db.commit()
        return True

    async def _send_shift_code_email(
        self, to_email: str, point_name: str, employee_name: str, code: str
    ) -> None:
        s = self.settings
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Код открытия смены: {code}"
        msg["From"] = s.smtp_from or s.smtp_user
        msg["To"] = to_email

        text_body = (
            f"Сотрудник {employee_name} открывает смену на точке «{point_name}».\n\n"
            f"Код подтверждения: {code}\n\n"
            f"Код действителен 10 минут.\n"
            f"Если смена не открывалась — игнорируйте письмо."
        )
        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px">
          <h2 style="color:#333">Открытие смены</h2>
          <p>Сотрудник: <strong>{employee_name}</strong></p>
          <p>Точка: <strong>{point_name}</strong></p>
          <p>Код подтверждения:</p>
          <div style="font-size:40px;font-weight:bold;letter-spacing:12px;
                      padding:16px 24px;background:#f5f5f5;border-radius:8px;
                      display:inline-block;margin:12px 0;color:#1e293b">{code}</div>
          <p style="color:#666;font-size:13px">
            Код действителен 10 минут.<br>
            Если смена не открывалась — игнорируйте письмо.
          </p>
        </div>
        """
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_user,
                password=s.smtp_password,
                use_tls=True,
            )
            log.info("Shift code email sent to %s (point=%s)", to_email, point_name)
        except Exception as exc:
            log.error("Failed to send shift code to %s: %s", to_email, exc)
            raise

    async def _send_email(self, to_email: str, operation: str, code: str) -> None:
        label = OPERATION_LABELS.get(operation, operation)
        s = self.settings

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Код подтверждения: {code}"
        msg["From"] = s.smtp_from or s.smtp_user
        msg["To"] = to_email

        text_body = (
            f"Код подтверждения операции «{label}»:\n\n"
            f"    {code}\n\n"
            f"Код действителен {s.email_code_ttl_minutes} минут.\n"
            f"Если вы не запрашивали этот код — игнорируйте письмо."
        )
        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px">
          <h2 style="color:#333">Код подтверждения</h2>
          <p>Операция: <strong>{label}</strong></p>
          <div style="font-size:32px;font-weight:bold;letter-spacing:8px;
                      padding:16px 24px;background:#f5f5f5;border-radius:8px;
                      display:inline-block;margin:12px 0">{code}</div>
          <p style="color:#666;font-size:13px">
            Код действителен {s.email_code_ttl_minutes} минут.<br>
            Если вы не запрашивали этот код — игнорируйте письмо.
          </p>
        </div>
        """
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_user,
                password=s.smtp_password,
                use_tls=True,
            )
            log.info("Confirmation email sent to %s (operation=%s)", to_email, operation)
        except Exception as exc:
            log.error("Failed to send email to %s: %s", to_email, exc)
            raise
