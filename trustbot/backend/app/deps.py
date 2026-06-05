"""Shared FastAPI dependencies.

``get_current_org`` is the single tenancy seam: the MVP is single-tenant, so it returns
the one seeded org, but every product route depends on it (not on a client-supplied id),
so adding real auth later means changing only this function — queries already scope by
the org it returns.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .db.models import Organization


def get_current_org(session: Session = Depends(get_session)) -> Organization:
    org = session.scalar(select(Organization).limit(1))
    if org is None:
        raise HTTPException(status_code=404, detail="No organization is seeded yet")
    return org
