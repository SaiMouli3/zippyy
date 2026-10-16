"""Customers, addresses and consent. The only module that sees decrypted PII, and only on demand."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform import audit, clock
from app.platform.models import Address, ConsentRecord, Customer
from app.platform.security import crypto


@dataclass
class CustomerInput:
    name: str
    phone: str
    email: str | None = None
    line1: str = ""
    line2: str | None = None
    landmark: str | None = None
    city: str = ""
    state: str = ""
    pincode: str = ""
    whatsapp_consent_evidence: str | None = None  # e.g. "checkout opt-in checkbox, order #1042"
    voice_consent_evidence: str | None = None


def upsert_customer(db: Session, merchant_id: str, data: CustomerInput) -> tuple[Customer, Address]:
    phone = crypto.normalize_phone(data.phone)
    h = crypto.phone_hash(phone)
    customer = db.scalars(select(Customer).where(Customer.merchant_id == merchant_id, Customer.phone_hash == h)).first()
    if customer is None:
        customer = Customer(merchant_id=merchant_id, name=data.name.strip()[:200],
                            phone_enc=crypto.encrypt(phone, "customers.phone"), phone_hash=h, phone_last4=phone[-4:],
                            email_enc=crypto.encrypt(data.email, "customers.email") if data.email else None)
        db.add(customer)
        db.flush()
    else:
        customer.name = data.name.strip()[:200] or customer.name
    address = Address(merchant_id=merchant_id, customer_id=customer.id,
                      line1_enc=crypto.encrypt(data.line1 or "-", "addresses.line1"),
                      line2_enc=crypto.encrypt(data.line2, "addresses.line2") if data.line2 else None,
                      landmark_enc=crypto.encrypt(data.landmark, "addresses.landmark") if data.landmark else None,
                      city=data.city[:100], state=data.state[:100], pincode=data.pincode[:6],
                      quality="unverified")
    db.add(address)
    if data.whatsapp_consent_evidence:
        record_consent(db, customer, "whatsapp", "granted", "api_import", data.whatsapp_consent_evidence)
    if data.voice_consent_evidence:
        record_consent(db, customer, "voice", "granted", "api_import", data.voice_consent_evidence)
    db.flush()
    return customer, address


def record_consent(db: Session, customer: Customer, channel: str, status: str, source: str, evidence: str,
                   recorded_by: str | None = None) -> ConsentRecord:
    row = ConsentRecord(merchant_id=customer.merchant_id, customer_id=customer.id, channel=channel, status=status,
                        source=source, evidence=evidence[:300], recorded_by=recorded_by)
    db.add(row)
    return row


def record_opt_out(db: Session, customer: Customer, source: str, actor: audit.Actor, evidence: str) -> None:
    if customer.opted_out_at is not None:
        return
    customer.opted_out_at = clock.now()
    customer.opt_out_source = source
    for channel in ("whatsapp", "voice"):
        record_consent(db, customer, channel, "revoked", source, evidence)
    audit.record(db, actor, customer.merchant_id, "customer", customer.id, "customer.opted_out", reason=evidence)


def phone_e164(customer: Customer) -> str:
    """Decrypt for sending only. Never log or return this to the browser without an unmask audit."""
    return crypto.decrypt(customer.phone_enc, "customers.phone")


def first_name(customer: Customer) -> str:
    return (customer.name or "there").split()[0][:30]


def masked(customer: Customer) -> dict:
    return {"id": customer.id, "name": customer.name, "phoneMasked": crypto.mask_phone(customer.phone_last4),
            "preferredLanguage": customer.preferred_language,
            "preferredLanguageSource": customer.preferred_language_source,
            "predictedLanguage": customer.predicted_language,
            "predictedLanguageSource": customer.predicted_language_source,
            "predictedLanguageConfidence": customer.predicted_language_confidence,
            "optedOut": customer.opted_out_at is not None, "optedOutAt": customer.opted_out_at}


def masked_address(address: Address | None) -> dict | None:
    if address is None:
        return None
    return {"id": address.id, "line1Masked": crypto.mask_text(crypto.decrypt(address.line1_enc, "addresses.line1"), 4),
            "city": address.city, "state": address.state, "pincode": address.pincode, "quality": address.quality}


def unmask(db: Session, customer: Customer, address: Address | None, actor: audit.Actor, reason: str) -> dict:
    """Full PII for an authorized operator. Always audited, with the stated reason."""
    audit.record(db, actor, customer.merchant_id, "customer", customer.id, "pii.unmasked", reason=reason[:500])
    out = {"phone": phone_e164(customer),
           "email": crypto.decrypt(customer.email_enc, "customers.email") if customer.email_enc else None}
    if address is not None:
        out["address"] = {
            "line1": crypto.decrypt(address.line1_enc, "addresses.line1"),
            "line2": crypto.decrypt(address.line2_enc, "addresses.line2") if address.line2_enc else None,
            "landmark": crypto.decrypt(address.landmark_enc, "addresses.landmark") if address.landmark_enc else None,
            "city": address.city, "state": address.state, "pincode": address.pincode,
        }
    return out


def erase(db: Session, customer: Customer, actor: audit.Actor, reason: str) -> None:
    """DPDP erasure: null the PII, keep shipment/case/ledger rows for legal and operational history."""
    customer.name = "Erased customer"
    customer.phone_enc = crypto.encrypt("+910000000000", "customers.phone")
    customer.email_enc = None
    customer.pii_erased_at = clock.now()
    for a in db.scalars(select(Address).where(Address.customer_id == customer.id)):
        a.line1_enc = crypto.encrypt("[erased]", "addresses.line1")
        a.line2_enc = None
        a.landmark_enc = None
    audit.record(db, actor, customer.merchant_id, "customer", customer.id, "pii.erased", reason=reason)
