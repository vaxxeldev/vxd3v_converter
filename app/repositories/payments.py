from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import aiosqlite

from app.services.errors import InsufficientBalanceError, PaymentStateError


class PaymentStatus(StrEnum):
    AWAITING_RECEIPT = "awaiting_receipt"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    CANCELED = "canceled"


class RenderStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    REFUNDED = "refunded"


class CryptoInvoiceStatus(StrEnum):
    ACTIVE = "active"
    PAID = "paid"
    EXPIRED = "expired"


@dataclass(slots=True, frozen=True)
class PaymentRequest:
    id: str
    user_id: int
    amount_kopecks: int
    status: PaymentStatus
    receipt_file_id: str | None = None
    receipt_kind: str | None = None


@dataclass(slots=True, frozen=True)
class ApprovalResult:
    payment: PaymentRequest
    applied: bool
    balance_kopecks: int


@dataclass(slots=True, frozen=True)
class RenderOrder:
    id: str
    user_id: int
    amount_kopecks: int
    admin_credit_kopecks: int = 0
    regular_kopecks: int = 0


@dataclass(slots=True, frozen=True)
class CryptoInvoiceRecord:
    invoice_id: int
    user_id: int
    amount_kopecks: int
    status: CryptoInvoiceStatus
    pay_url: str


@dataclass(slots=True, frozen=True)
class BotStatistics:
    users_total: int
    users_today: int
    users_seven_days: int
    renders_completed: int
    renders_today: int
    renders_seven_days: int
    renders_refunded: int
    countable_balance_kopecks: int
    direct_topups_kopecks: int
    crypto_topups_kopecks: int
    payments_awaiting_review: int
    crypto_invoices_active: int

    @property
    def successful_render_percent(self) -> float:
        finished = self.renders_completed + self.renders_refunded
        return 0.0 if finished == 0 else self.renders_completed / finished * 100

    @property
    def renders_per_user(self) -> float:
        return 0.0 if self.users_total == 0 else self.renders_completed / self.users_total


class PaymentRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._database_path.parent.mkdir, parents=True, exist_ok=True)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS payment_requests (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES user_settings(user_id),
                    amount_kopecks INTEGER NOT NULL CHECK(amount_kopecks >= 1000),
                    method TEXT NOT NULL CHECK(method = 'direct'),
                    status TEXT NOT NULL,
                    receipt_file_id TEXT,
                    receipt_kind TEXT,
                    admin_message_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS payment_requests_user_status
                ON payment_requests(user_id, status);
                CREATE TABLE IF NOT EXISTS balance_transactions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES user_settings(user_id),
                    amount_kopecks INTEGER NOT NULL CHECK(amount_kopecks <> 0),
                    kind TEXT NOT NULL,
                    reference_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(kind, reference_id)
                );
                CREATE TABLE IF NOT EXISTS render_orders (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES user_settings(user_id),
                    amount_kopecks INTEGER NOT NULL CHECK(amount_kopecks > 0),
                    status TEXT NOT NULL,
                    admin_credit_kopecks INTEGER NOT NULL DEFAULT 0,
                    regular_kopecks INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS crypto_invoices (
                    invoice_id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES user_settings(user_id),
                    amount_kopecks INTEGER NOT NULL CHECK(amount_kopecks >= 1000),
                    status TEXT NOT NULL,
                    pay_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS crypto_invoices_status
                ON crypto_invoices(status);
                """
            )
            await self._ensure_accounting_columns(connection)
            await self._rebuild_admin_credit_balances(connection)
            await connection.commit()

    @staticmethod
    async def _ensure_accounting_columns(connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA table_info(render_orders)")
        columns = {str(row[1]) for row in await cursor.fetchall()}
        if "admin_credit_kopecks" not in columns:
            await connection.execute(
                "ALTER TABLE render_orders ADD COLUMN admin_credit_kopecks "
                "INTEGER NOT NULL DEFAULT 0"
            )
        if "regular_kopecks" not in columns:
            await connection.execute(
                "ALTER TABLE render_orders ADD COLUMN regular_kopecks "
                "INTEGER NOT NULL DEFAULT 0"
            )

    @staticmethod
    async def _rebuild_admin_credit_balances(connection: aiosqlite.Connection) -> None:
        users_cursor = await connection.execute(
            "SELECT user_id, balance_kopecks FROM user_settings"
        )
        for user_id, balance_kopecks in await users_cursor.fetchall():
            transactions_cursor = await connection.execute(
                "SELECT kind, amount_kopecks, reference_id FROM balance_transactions "
                "WHERE user_id = ? ORDER BY created_at, rowid",
                (user_id,),
            )
            admin_balance = 0
            order_admin_amounts: dict[str, int] = {}
            for kind, amount_kopecks, reference_id in await transactions_cursor.fetchall():
                amount = int(amount_kopecks)
                reference = str(reference_id)
                if kind == "admin_credit":
                    admin_balance += amount
                elif kind == "render_charge":
                    admin_used = min(admin_balance, -amount)
                    admin_balance -= admin_used
                    order_admin_amounts[reference] = admin_used
                    await connection.execute(
                        "UPDATE render_orders SET admin_credit_kopecks = ?, "
                        "regular_kopecks = amount_kopecks - ? WHERE id = ?",
                        (admin_used, admin_used, reference),
                    )
                elif kind == "render_refund":
                    admin_balance += order_admin_amounts.get(reference, 0)
            admin_balance = min(max(admin_balance, 0), int(balance_kopecks))
            await connection.execute(
                "UPDATE user_settings SET admin_credit_balance_kopecks = ? WHERE user_id = ?",
                (admin_balance, user_id),
            )

    async def create_direct(self, user_id: int, amount_kopecks: int) -> PaymentRequest:
        payment_id = uuid.uuid4().hex[:16]
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "UPDATE payment_requests SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ? AND status = ?",
                (PaymentStatus.CANCELED, user_id, PaymentStatus.AWAITING_RECEIPT),
            )
            await connection.execute(
                "INSERT INTO payment_requests "
                "(id, user_id, amount_kopecks, method, status) VALUES (?, ?, ?, 'direct', ?)",
                (payment_id, user_id, amount_kopecks, PaymentStatus.AWAITING_RECEIPT),
            )
            await connection.commit()
        return PaymentRequest(payment_id, user_id, amount_kopecks, PaymentStatus.AWAITING_RECEIPT)

    async def attach_receipt(
        self,
        payment_id: str,
        user_id: int,
        file_id: str,
        receipt_kind: str,
    ) -> PaymentRequest:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT * FROM payment_requests WHERE id = ? AND user_id = ?",
                (payment_id, user_id),
            )
            row = await cursor.fetchone()
            if row is None or row["status"] != PaymentStatus.AWAITING_RECEIPT:
                await connection.rollback()
                raise PaymentStateError("Заявка уже закрыта или не найдена.")
            await connection.execute(
                "UPDATE payment_requests SET status = ?, receipt_file_id = ?, "
                "receipt_kind = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (PaymentStatus.AWAITING_REVIEW, file_id, receipt_kind, payment_id),
            )
            await connection.commit()
        return PaymentRequest(
            payment_id,
            user_id,
            int(row["amount_kopecks"]),
            PaymentStatus.AWAITING_REVIEW,
            file_id,
            receipt_kind,
        )

    async def cancel(self, payment_id: str, user_id: int) -> bool:
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "UPDATE payment_requests SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ? AND status = ?",
                (
                    PaymentStatus.CANCELED,
                    payment_id,
                    user_id,
                    PaymentStatus.AWAITING_RECEIPT,
                ),
            )
            await connection.commit()
        return cursor.rowcount == 1

    async def set_admin_message(self, payment_id: str, message_id: int) -> None:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE payment_requests SET admin_message_id = ? WHERE id = ?",
                (message_id, payment_id),
            )
            await connection.commit()

    async def approve(self, payment_id: str) -> ApprovalResult:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT * FROM payment_requests WHERE id = ?",
                (payment_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.rollback()
                raise PaymentStateError("Заявка не найдена.")
            payment = self._payment(row)
            applied = payment.status is PaymentStatus.AWAITING_REVIEW
            if applied:
                await connection.execute(
                    "UPDATE payment_requests SET status = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = ?",
                    (PaymentStatus.APPROVED, payment_id, PaymentStatus.AWAITING_REVIEW),
                )
                await connection.execute(
                    "UPDATE user_settings SET balance_kopecks = balance_kopecks + ? "
                    "WHERE user_id = ?",
                    (payment.amount_kopecks, payment.user_id),
                )
                await connection.execute(
                    "INSERT INTO balance_transactions "
                    "(id, user_id, amount_kopecks, kind, reference_id) "
                    "VALUES (?, ?, ?, 'topup', ?)",
                    (uuid.uuid4().hex, payment.user_id, payment.amount_kopecks, payment.id),
                )
                payment = PaymentRequest(
                    payment.id,
                    payment.user_id,
                    payment.amount_kopecks,
                    PaymentStatus.APPROVED,
                    payment.receipt_file_id,
                    payment.receipt_kind,
                )
            balance_cursor = await connection.execute(
                "SELECT balance_kopecks FROM user_settings WHERE user_id = ?",
                (payment.user_id,),
            )
            balance_row = await balance_cursor.fetchone()
            await connection.commit()
        return ApprovalResult(payment, applied, int(balance_row[0]))

    async def charge_render(self, user_id: int, amount_kopecks: int) -> RenderOrder:
        order_id = uuid.uuid4().hex
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            balance_cursor = await connection.execute(
                "SELECT balance_kopecks, admin_credit_balance_kopecks "
                "FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            balance = await balance_cursor.fetchone()
            if balance is None or int(balance["balance_kopecks"]) < amount_kopecks:
                await connection.rollback()
                raise InsufficientBalanceError("Недостаточно средств для рендера.")
            admin_used = min(int(balance["admin_credit_balance_kopecks"]), amount_kopecks)
            regular_used = amount_kopecks - admin_used
            await connection.execute(
                "UPDATE user_settings SET balance_kopecks = balance_kopecks - ?, "
                "admin_credit_balance_kopecks = admin_credit_balance_kopecks - ? "
                "WHERE user_id = ?",
                (amount_kopecks, admin_used, user_id),
            )
            await connection.execute(
                "INSERT INTO render_orders "
                "(id, user_id, amount_kopecks, status, admin_credit_kopecks, regular_kopecks) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    order_id,
                    user_id,
                    amount_kopecks,
                    RenderStatus.PROCESSING,
                    admin_used,
                    regular_used,
                ),
            )
            await connection.execute(
                "INSERT INTO balance_transactions "
                "(id, user_id, amount_kopecks, kind, reference_id) "
                "VALUES (?, ?, ?, 'render_charge', ?)",
                (uuid.uuid4().hex, user_id, -amount_kopecks, order_id),
            )
            await connection.commit()
        return RenderOrder(order_id, user_id, amount_kopecks, admin_used, regular_used)

    async def admin_credit(self, user_id: int, amount_kopecks: int) -> int:
        if amount_kopecks <= 0:
            raise PaymentStateError("Сумма начисления должна быть больше нуля.")
        reference_id = uuid.uuid4().hex
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "UPDATE user_settings SET balance_kopecks = balance_kopecks + ?, "
                "admin_credit_balance_kopecks = admin_credit_balance_kopecks + ? "
                "WHERE user_id = ?",
                (amount_kopecks, amount_kopecks, user_id),
            )
            if cursor.rowcount != 1:
                await connection.rollback()
                raise PaymentStateError("Пользователь не найден.")
            await connection.execute(
                "INSERT INTO balance_transactions "
                "(id, user_id, amount_kopecks, kind, reference_id) "
                "VALUES (?, ?, ?, 'admin_credit', ?)",
                (uuid.uuid4().hex, user_id, amount_kopecks, reference_id),
            )
            balance_cursor = await connection.execute(
                "SELECT balance_kopecks FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            balance = await balance_cursor.fetchone()
            await connection.commit()
        return int(balance[0])

    async def create_crypto_invoice(
        self,
        invoice_id: int,
        user_id: int,
        amount_kopecks: int,
        pay_url: str,
    ) -> CryptoInvoiceRecord:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "INSERT INTO crypto_invoices "
                "(invoice_id, user_id, amount_kopecks, status, pay_url) "
                "VALUES (?, ?, ?, ?, ?)",
                (invoice_id, user_id, amount_kopecks, CryptoInvoiceStatus.ACTIVE, pay_url),
            )
            await connection.commit()
        return CryptoInvoiceRecord(
            invoice_id,
            user_id,
            amount_kopecks,
            CryptoInvoiceStatus.ACTIVE,
            pay_url,
        )

    async def active_crypto_invoices(self) -> list[CryptoInvoiceRecord]:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM crypto_invoices WHERE status = ? ORDER BY invoice_id",
                (CryptoInvoiceStatus.ACTIVE,),
            )
            rows = await cursor.fetchall()
        return [self._crypto_invoice(row) for row in rows]

    async def settle_crypto_invoice(self, invoice_id: int, status: str) -> tuple[bool, int, int]:
        if status not in {CryptoInvoiceStatus.PAID, CryptoInvoiceStatus.EXPIRED}:
            raise PaymentStateError("Некорректный статус Crypto Bot.")
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT * FROM crypto_invoices WHERE invoice_id = ?",
                (invoice_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.rollback()
                raise PaymentStateError("Счёт Crypto Bot не найден.")
            applied = row["status"] == CryptoInvoiceStatus.ACTIVE
            if applied:
                await connection.execute(
                    "UPDATE crypto_invoices SET status = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE invoice_id = ? AND status = ?",
                    (status, invoice_id, CryptoInvoiceStatus.ACTIVE),
                )
                if status == CryptoInvoiceStatus.PAID:
                    await connection.execute(
                        "UPDATE user_settings SET balance_kopecks = balance_kopecks + ? "
                        "WHERE user_id = ?",
                        (row["amount_kopecks"], row["user_id"]),
                    )
                    await connection.execute(
                        "INSERT INTO balance_transactions "
                        "(id, user_id, amount_kopecks, kind, reference_id) "
                        "VALUES (?, ?, ?, 'crypto_topup', ?)",
                        (
                            uuid.uuid4().hex,
                            row["user_id"],
                            row["amount_kopecks"],
                            str(invoice_id),
                        ),
                    )
            balance_cursor = await connection.execute(
                "SELECT balance_kopecks FROM user_settings WHERE user_id = ?",
                (row["user_id"],),
            )
            balance = await balance_cursor.fetchone()
            await connection.commit()
        return applied, int(row["user_id"]), int(balance[0])

    async def complete_render(self, order_id: str) -> None:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE render_orders SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = ?",
                (RenderStatus.COMPLETED, order_id, RenderStatus.PROCESSING),
            )
            await connection.commit()

    async def refund_render(self, order_id: str) -> bool:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT * FROM render_orders WHERE id = ?",
                (order_id,),
            )
            row = await cursor.fetchone()
            if row is None or row["status"] != RenderStatus.PROCESSING:
                await connection.rollback()
                return False
            await connection.execute(
                "UPDATE render_orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (RenderStatus.REFUNDED, order_id),
            )
            await connection.execute(
                "UPDATE user_settings SET balance_kopecks = balance_kopecks + ?, "
                "admin_credit_balance_kopecks = admin_credit_balance_kopecks + ? "
                "WHERE user_id = ?",
                (row["amount_kopecks"], row["admin_credit_kopecks"], row["user_id"]),
            )
            await connection.execute(
                "INSERT INTO balance_transactions "
                "(id, user_id, amount_kopecks, kind, reference_id) "
                "VALUES (?, ?, ?, 'render_refund', ?)",
                (uuid.uuid4().hex, row["user_id"], row["amount_kopecks"], order_id),
            )
            await connection.commit()
        return True

    async def statistics(self, admin_id: int) -> BotStatistics:
        async with aiosqlite.connect(self._database_path) as connection:
            async def scalar(query: str, parameters: tuple[object, ...] = ()) -> int:
                cursor = await connection.execute(query, parameters)
                row = await cursor.fetchone()
                return 0 if row is None or row[0] is None else int(row[0])

            user_filter = "user_id <> ?"
            users_total = await scalar(
                f"SELECT COUNT(*) FROM user_settings WHERE {user_filter}",  # noqa: S608
                (admin_id,),
            )
            users_today = await scalar(
                "SELECT COUNT(*) FROM user_settings WHERE user_id <> ? "
                "AND date(created_at, '+5 hours') = date('now', '+5 hours')",
                (admin_id,),
            )
            users_seven_days = await scalar(
                "SELECT COUNT(*) FROM user_settings WHERE user_id <> ? "
                "AND created_at >= datetime('now', '-7 days')",
                (admin_id,),
            )
            renders_completed = await scalar(
                "SELECT COUNT(*) FROM render_orders WHERE user_id <> ? AND status = ?",
                (admin_id, RenderStatus.COMPLETED),
            )
            renders_today = await scalar(
                "SELECT COUNT(*) FROM render_orders WHERE user_id <> ? AND status = ? "
                "AND date(updated_at, '+5 hours') = date('now', '+5 hours')",
                (admin_id, RenderStatus.COMPLETED),
            )
            renders_seven_days = await scalar(
                "SELECT COUNT(*) FROM render_orders WHERE user_id <> ? AND status = ? "
                "AND updated_at >= datetime('now', '-7 days')",
                (admin_id, RenderStatus.COMPLETED),
            )
            renders_refunded = await scalar(
                "SELECT COUNT(*) FROM render_orders WHERE user_id <> ? AND status = ?",
                (admin_id, RenderStatus.REFUNDED),
            )
            countable_balance = await scalar(
                "SELECT COALESCE(SUM(balance_kopecks - admin_credit_balance_kopecks), 0) "
                "FROM user_settings WHERE user_id <> ?",
                (admin_id,),
            )
            direct_topups = await scalar(
                "SELECT COALESCE(SUM(amount_kopecks), 0) FROM balance_transactions "
                "WHERE user_id <> ? AND kind = 'topup'",
                (admin_id,),
            )
            crypto_topups = await scalar(
                "SELECT COALESCE(SUM(amount_kopecks), 0) FROM balance_transactions "
                "WHERE user_id <> ? AND kind = 'crypto_topup'",
                (admin_id,),
            )
            awaiting_review = await scalar(
                "SELECT COUNT(*) FROM payment_requests WHERE user_id <> ? AND status = ?",
                (admin_id, PaymentStatus.AWAITING_REVIEW),
            )
            active_crypto = await scalar(
                "SELECT COUNT(*) FROM crypto_invoices WHERE user_id <> ? AND status = ?",
                (admin_id, CryptoInvoiceStatus.ACTIVE),
            )
        return BotStatistics(
            users_total,
            users_today,
            users_seven_days,
            renders_completed,
            renders_today,
            renders_seven_days,
            renders_refunded,
            countable_balance,
            direct_topups,
            crypto_topups,
            awaiting_review,
            active_crypto,
        )

    async def refund_interrupted_renders(self) -> int:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT id FROM render_orders WHERE status = ?",
                (RenderStatus.PROCESSING,),
            )
            order_ids = [str(row[0]) for row in await cursor.fetchall()]
        refunded = 0
        for order_id in order_ids:
            refunded += int(await self.refund_render(order_id))
        return refunded

    @staticmethod
    def _payment(row: aiosqlite.Row) -> PaymentRequest:
        return PaymentRequest(
            id=str(row["id"]),
            user_id=int(row["user_id"]),
            amount_kopecks=int(row["amount_kopecks"]),
            status=PaymentStatus(row["status"]),
            receipt_file_id=row["receipt_file_id"],
            receipt_kind=row["receipt_kind"],
        )

    @staticmethod
    def _crypto_invoice(row: aiosqlite.Row) -> CryptoInvoiceRecord:
        return CryptoInvoiceRecord(
            invoice_id=int(row["invoice_id"]),
            user_id=int(row["user_id"]),
            amount_kopecks=int(row["amount_kopecks"]),
            status=CryptoInvoiceStatus(row["status"]),
            pay_url=str(row["pay_url"]),
        )
