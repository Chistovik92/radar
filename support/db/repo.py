"""Операции с тикетами; проверка доступа выполняется в каждом публичном методе."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from ..core import roles, sla
from .engine import Database
from .models import Meta, Ticket, TicketMessage, User, utcnow

NUMBER_RE = re.compile(r"^#?(\d{4})-(\d+)$")
ACTIVE_PREFIX = "active_ticket:"
FAQ_KEY = "faq"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def ticket_number(ticket: Ticket) -> str:
    return f"#{_utc(ticket.created_at).year}-{ticket.id}"


def parse_number(value: str) -> tuple[int, int] | None:
    match = NUMBER_RE.fullmatch((value or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def subject_from(text: str) -> str:
    clean = " ".join((text or "").split())
    return clean[:197] + "…" if len(clean) > 197 else clean


class TicketClosed(RuntimeError):
    pass


class SupportRepository:
    def __init__(self, database: Database, sla_minutes: int = 60) -> None:
        self.db = database
        self.sla_minutes = sla_minutes

    async def _user(self, active, external_id: int) -> User | None:
        return await active.scalar(select(User).where(User.external_id == external_id))

    async def get_or_create_user(self, external_id: int, username: str = "", lang: str = "ru",
                                 superadmin_id: int = 0) -> User:
        async with self.db.session() as active:
            user = await self._user(active, external_id)
            if user is None:
                user = User(
                    external_id=external_id,
                    username=(username or "")[:64],
                    lang=lang if lang in {"ru", "en"} else "ru",
                    role=roles.SUPERADMIN if external_id == superadmin_id else roles.USER,
                )
                active.add(user)
            else:
                user.username = (username or "")[:64]
                if external_id == superadmin_id:
                    user.role = roles.SUPERADMIN
            await active.flush()
            return user

    async def get_user(self, external_id: int) -> User | None:
        async with self.db.session() as active:
            return await self._user(active, external_id)

    async def create_ticket(self, author_external_id: int, subject: str = "", category: str = "",
                            group_id: int | None = None, thread_id: int | None = None,
                            now: datetime | None = None) -> Ticket:
        created = now or utcnow()
        async with self.db.session() as active:
            author = await self._user(active, author_external_id)
            if author is None:
                raise ValueError("Сначала зарегистрируйте пользователя")
            ticket = Ticket(
                author_id=author.id,
                subject=subject_from(subject),
                category=category,
                sla_due_at=sla.deadline(created, self.sla_minutes),
                created_at=created,
                updated_at=created,
                group_id=group_id,
                thread_id=thread_id,
            )
            active.add(ticket)
            await active.flush()
            await self._set_active(active, author.id, ticket.id)
            return ticket

    async def _set_active(self, active, user_id: int, ticket_id: int) -> None:
        key = ACTIVE_PREFIX + str(user_id)
        meta = await active.get(Meta, key)
        if meta is None:
            active.add(Meta(key=key, value={"id": ticket_id}))
        else:
            meta.value = {"id": ticket_id}

    @staticmethod
    def _can_read(user: User, ticket: Ticket) -> bool:
        return ticket.author_id == user.id or roles.is_moderator(user.role)

    async def _accessible(self, active, reference: str | int, actor_external_id: int) -> tuple[User, Ticket] | None:
        if isinstance(reference, int):
            ticket_id, year = reference, None
        else:
            parsed = parse_number(str(reference))
            if parsed is None:
                return None
            year, ticket_id = parsed
        user = await self._user(active, actor_external_id)
        ticket = await active.get(Ticket, ticket_id)
        if user is None or ticket is None or not self._can_read(user, ticket):
            return None
        if year is not None and _utc(ticket.created_at).year != year:
            return None
        return user, ticket

    async def get_ticket(self, reference: str | int, actor_external_id: int) -> Ticket | None:
        async with self.db.session() as active:
            found = await self._accessible(active, reference, actor_external_id)
            return found[1] if found else None

    async def set_active(self, reference: str | int, actor_external_id: int) -> Ticket | None:
        async with self.db.session() as active:
            found = await self._accessible(active, reference, actor_external_id)
            if found is None:
                return None
            user, ticket = found
            await self._set_active(active, user.id, ticket.id)
            return ticket

    async def active_ticket(self, actor_external_id: int) -> Ticket | None:
        async with self.db.session() as active:
            user = await self._user(active, actor_external_id)
            if user is None:
                return None
            meta = await active.get(Meta, ACTIVE_PREFIX + str(user.id))
            ticket_id = int((meta.value if meta else {}).get("id", 0) or 0)
            ticket = await active.get(Ticket, ticket_id) if ticket_id else None
            if ticket is None or not self._can_read(user, ticket):
                return None
            return ticket

    async def by_topic(self, group_id: int, thread_id: int, actor_external_id: int) -> Ticket | None:
        async with self.db.session() as active:
            user = await self._user(active, actor_external_id)
            ticket = await active.scalar(select(Ticket).where(
                Ticket.group_id == group_id, Ticket.thread_id == thread_id
            ))
            if user is None or ticket is None or not self._can_read(user, ticket):
                return None
            return ticket

    async def list_tickets(self, actor_external_id: int, include_closed: bool = False,
                           limit: int = 50) -> list[Ticket]:
        async with self.db.session() as active:
            user = await self._user(active, actor_external_id)
            if user is None:
                return []
            query = select(Ticket)
            if not roles.is_moderator(user.role):
                query = query.where(Ticket.author_id == user.id)
            if not include_closed:
                query = query.where(Ticket.status != "closed")
            query = query.order_by(Ticket.updated_at.desc()).limit(max(1, min(limit, 200)))
            return list((await active.scalars(query)).all())

    async def by_topic_any(self, group_id: int, thread_id: int) -> Ticket | None:
        """Технический lookup для группы; чтение содержимого всё равно требует доступа."""
        async with self.db.session() as active:
            return await active.scalar(select(Ticket).where(
                Ticket.group_id == group_id, Ticket.thread_id == thread_id
            ))

    async def add_message(self, reference: str | int, sender_external_id: int, body: str = "",
                          kind: str = "text", attachment: Any = None,
                          now: datetime | None = None) -> tuple[Ticket, TicketMessage] | None:
        created = now or utcnow()
        async with self.db.session() as active:
            found = await self._accessible(active, reference, sender_external_id)
            if found is None:
                return None
            sender, ticket = found
            if ticket.status == "closed":
                raise TicketClosed(ticket_number(ticket))
            operator = roles.is_moderator(sender.role) and sender.id != ticket.author_id
            if operator:
                ticket.status = "answered"
                ticket.assignee_id = sender.id
                if ticket.first_response_at is None:
                    ticket.first_response_at = created
            elif sender.id == ticket.author_id and ticket.status == "answered":
                ticket.status = "open"
            if not ticket.subject and body:
                ticket.subject = subject_from(body)
            if not ticket.category and body:
                from ..core.classify import classify
                ticket.category = classify(body)
            message = TicketMessage(
                ticket_id=ticket.id,
                sender_id=sender.id,
                kind=kind,
                body=body or "",
                attachment_file_id=getattr(attachment, "file_id", "") or "",
                attachment_type=getattr(attachment, "kind", "") or "",
                attachment_name=getattr(attachment, "name", "") or "",
                created_at=created,
            )
            ticket.updated_at = created
            active.add(message)
            await active.flush()
            return ticket, message

    async def add_system_message(self, ticket_id: int, body: str,
                                 now: datetime | None = None) -> TicketMessage:
        async with self.db.session() as active:
            message = TicketMessage(
                ticket_id=ticket_id, sender_id=None, kind="system", body=body,
                created_at=now or utcnow(),
            )
            active.add(message)
            await active.flush()
            return message

    async def close_ticket(self, reference: str | int, actor_external_id: int,
                           now: datetime | None = None) -> Ticket | None:
        closed = now or utcnow()
        async with self.db.session() as active:
            found = await self._accessible(active, reference, actor_external_id)
            if found is None:
                return None
            user, ticket = found
            if ticket.status == "closed":
                return ticket
            ticket.status = "closed"
            ticket.closed_at = closed
            ticket.updated_at = closed
            active.add(TicketMessage(
                ticket_id=ticket.id, sender_id=None, kind="system",
                body=f"тикет закрыт пользователем id {user.external_id}", created_at=closed,
            ))
            await active.flush()
            return ticket

    async def rate_ticket(self, reference: str | int, author_external_id: int,
                          rating: int, now: datetime | None = None) -> bool:
        if rating not in {-1, 1}:
            return False
        async with self.db.session() as active:
            found = await self._accessible(active, reference, author_external_id)
            if found is None:
                return False
            user, ticket = found
            if ticket.author_id != user.id or ticket.status != "closed":
                return False
            ticket.rating = rating
            ticket.rated_at = now or utcnow()
            return True

    async def set_priority(self, reference: str | int, actor_external_id: int,
                           priority: str) -> Ticket | None:
        if priority not in {"low", "normal", "high"}:
            return None
        async with self.db.session() as active:
            found = await self._accessible(active, reference, actor_external_id)
            if found is None or not roles.is_moderator(found[0].role):
                return None
            found[1].priority = priority
            return found[1]

    async def bind_topic(self, reference: str | int, actor_external_id: int,
                         group_id: int, thread_id: int) -> Ticket | None:
        async with self.db.session() as active:
            found = await self._accessible(active, reference, actor_external_id)
            if found is None or not roles.is_moderator(found[0].role):
                return None
            found[1].group_id = group_id
            found[1].thread_id = thread_id
            return found[1]

    async def attach_topic(self, ticket_id: int, group_id: int, thread_id: int) -> Ticket | None:
        """Внутренняя привязка после успешного createForumTopic."""
        async with self.db.session() as active:
            ticket = await active.get(Ticket, ticket_id)
            if ticket is None:
                return None
            ticket.group_id = group_id
            ticket.thread_id = thread_id
            return ticket

    async def set_role(self, actor_external_id: int, target_external_id: int,
                       new_role: str) -> bool:
        async with self.db.session() as active:
            actor = await self._user(active, actor_external_id)
            target = await self._user(active, target_external_id)
            if actor is None or target is None or not roles.can_assign(actor.role, target.role, new_role):
                return False
            target.role = new_role
            return True

    async def faq_entries(self) -> dict[str, str]:
        async with self.db.session() as active:
            meta = await active.get(Meta, FAQ_KEY)
            return dict((meta.value if meta else {}).get("entries", {}))

    async def set_faq(self, actor_external_id: int, keyword: str, answer: str) -> bool:
        keyword, answer = keyword.strip().lower(), answer.strip()
        if not keyword or not answer:
            return False
        async with self.db.session() as active:
            actor = await self._user(active, actor_external_id)
            if actor is None or not roles.is_moderator(actor.role):
                return False
            meta = await active.get(Meta, FAQ_KEY)
            entries = dict((meta.value if meta else {}).get("entries", {}))
            entries[keyword] = answer
            if meta is None:
                active.add(Meta(key=FAQ_KEY, value={"entries": entries}))
            else:
                meta.value = {"entries": entries}
            return True

    async def delete_faq(self, actor_external_id: int, keyword: str) -> bool:
        async with self.db.session() as active:
            actor = await self._user(active, actor_external_id)
            if actor is None or not roles.is_moderator(actor.role):
                return False
            meta = await active.get(Meta, FAQ_KEY)
            entries = dict((meta.value if meta else {}).get("entries", {}))
            if keyword.strip().lower() not in entries:
                return False
            del entries[keyword.strip().lower()]
            meta.value = {"entries": entries}
            return True

    async def escalate_overdue(self, now: datetime | None = None) -> list[Ticket]:
        current = now or utcnow()
        async with self.db.session() as active:
            rows = list((await active.scalars(select(Ticket).where(
                Ticket.status == "open",
                Ticket.first_response_at.is_(None),
                Ticket.escalated_at.is_(None),
                Ticket.sla_due_at <= current,
            ))).all())
            for ticket in rows:
                ticket.priority = "high"
                ticket.escalated_at = current
                active.add(TicketMessage(
                    ticket_id=ticket.id, kind="system", sender_id=None,
                    body="SLA первого ответа просрочен; приоритет повышен до high",
                    created_at=current,
                ))
            await active.flush()
            return rows

    async def moderators(self) -> list[User]:
        async with self.db.session() as active:
            return list((await active.scalars(select(User).where(User.role.in_(
                [roles.MODERATOR, roles.ADMIN, roles.SUPERADMIN]
            )))).all())

    @staticmethod
    def _user_dict(user: User | None) -> dict[str, Any] | None:
        if user is None:
            return None
        return {"id": user.id, "external_id": user.external_id, "username": user.username}

    @staticmethod
    def _ticket_dict(ticket: Ticket) -> dict[str, Any]:
        return {
            "id": ticket.id, "number": ticket_number(ticket), "author_id": ticket.author_id,
            "subject": ticket.subject, "category": ticket.category, "status": ticket.status,
            "priority": ticket.priority, "created_at": ticket.created_at,
            "closed_at": ticket.closed_at, "sla_due_at": ticket.sla_due_at,
            "first_response_at": ticket.first_response_at, "rating": ticket.rating,
        }

    async def export_data(self, reference: str | int, actor_external_id: int) -> dict[str, Any] | None:
        async with self.db.session() as active:
            found = await self._accessible(active, reference, actor_external_id)
            if found is None:
                return None
            _, ticket = found
            author = await active.get(User, ticket.author_id)
            assignee = await active.get(User, ticket.assignee_id) if ticket.assignee_id else None
            rows = list((await active.scalars(select(TicketMessage).where(
                TicketMessage.ticket_id == ticket.id
            ).order_by(TicketMessage.created_at, TicketMessage.id))).all())
            sender_ids = {row.sender_id for row in rows if row.sender_id is not None}
            senders = {}
            if sender_ids:
                senders = {user.id: user for user in (await active.scalars(
                    select(User).where(User.id.in_(sender_ids))
                )).all()}
            messages = [{
                "kind": row.kind, "body": row.body, "created_at": row.created_at,
                "sender": self._user_dict(senders.get(row.sender_id)),
                "attachment_file_id": row.attachment_file_id,
                "attachment_type": row.attachment_type,
                "attachment_name": row.attachment_name,
            } for row in rows]
            return {
                "ticket": self._ticket_dict(ticket), "author": self._user_dict(author),
                "assignee": self._user_dict(assignee), "messages": messages,
            }

    async def statistics(self, actor_external_id: int) -> dict[str, Any] | None:
        async with self.db.session() as active:
            actor = await self._user(active, actor_external_id)
            if actor is None or not roles.is_moderator(actor.role):
                return None
            tickets = list((await active.scalars(select(Ticket))).all())
            users = list((await active.scalars(select(User))).all())
            by_id = {user.id: user for user in users}
            rated = [ticket for ticket in tickets if ticket.rating in {-1, 1}]
            positive = sum(ticket.rating == 1 for ticket in rated)
            by_operator: dict[str, list[int]] = {}
            by_category: dict[str, list[int]] = {}
            for ticket in rated:
                operator = self._user_dict(by_id.get(ticket.assignee_id))
                name = (operator or {}).get("username") or str((operator or {}).get("external_id", "не назначен"))
                by_operator.setdefault(name, [0, 0])[0 if ticket.rating == 1 else 1] += 1
                by_category.setdefault(ticket.category or "прочее", [0, 0])[0 if ticket.rating == 1 else 1] += 1
            responded = [ticket for ticket in tickets if ticket.first_response_at is not None]
            on_time = sum(
                _utc(ticket.first_response_at) <= _utc(ticket.sla_due_at)
                for ticket in responded
            )
            current = utcnow()
            overdue = sum(sla.is_overdue(
                _utc(ticket.sla_due_at), ticket.status,
                _utc(ticket.first_response_at) if ticket.first_response_at else None, current
            ) for ticket in tickets)
            return {
                "total": len(tickets),
                "statuses": {status: sum(ticket.status == status for ticket in tickets)
                             for status in ("open", "answered", "closed")},
                "rated": len(rated), "positive": positive, "negative": len(rated) - positive,
                "satisfaction": round(100 * positive / len(rated), 1) if rated else None,
                "by_operator": by_operator, "by_category": by_category,
                "sla_responded": len(responded), "sla_on_time": on_time, "sla_overdue_open": overdue,
            }

    async def delete_ticket(self, reference: str | int, actor_external_id: int) -> bool:
        async with self.db.session() as active:
            found = await self._accessible(active, reference, actor_external_id)
            if found is None or not roles.is_admin(found[0].role):
                return False
            ticket = found[1]
            await active.execute(delete(TicketMessage).where(TicketMessage.ticket_id == ticket.id))
            await active.delete(ticket)
            return True
