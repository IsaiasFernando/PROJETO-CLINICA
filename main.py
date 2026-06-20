import logging
import os
import re
import sys
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from supabase import Client, create_client


MESSAGE_TEMPLATE = "Olá, {name} tudo bem com você?"


@dataclass(frozen=True)
class Contact:
    name: str
    phone: str


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_key: str
    contacts_table: str
    name_column: str
    phone_column: str
    zapi_instance_id: str
    zapi_token: str
    zapi_client_token: str
    send_limit: int
    dry_run: bool


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Variável de ambiente obrigatória não encontrada: {name}")
    return value


def load_settings() -> Settings:
    load_dotenv()

    send_limit = int(os.getenv("SEND_LIMIT", "3"))
    send_limit = min(max(send_limit, 1), 3)

    return Settings(
        supabase_url=get_required_env("SUPABASE_URL"),
        supabase_key=get_required_env("SUPABASE_KEY"),
        contacts_table=os.getenv("CONTACTS_TABLE", "contacts"),
        name_column=os.getenv("NAME_COLUMN", "name"),
        phone_column=os.getenv("PHONE_COLUMN", "phone"),
        zapi_instance_id=get_required_env("ZAPI_INSTANCE_ID"),
        zapi_token=get_required_env("ZAPI_TOKEN"),
        zapi_client_token=get_required_env("ZAPI_CLIENT_TOKEN"),
        send_limit=send_limit,
        dry_run=os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"},
    )


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def fetch_contacts(supabase: Client, settings: Settings) -> list[Contact]:
    columns = f"{settings.name_column},{settings.phone_column}"
    response = (
        supabase.table(settings.contacts_table)
        .select(columns)
        .limit(settings.send_limit)
        .execute()
    )

    contacts: list[Contact] = []
    for row in response.data or []:
        name = str(row.get(settings.name_column, "")).strip()
        phone = normalize_phone(str(row.get(settings.phone_column, "")))

        if not name or not phone:
            logging.warning("Contato ignorado por falta de nome ou telefone: %s", row)
            continue

        contacts.append(Contact(name=name, phone=phone))

    return contacts


def send_message(contact: Contact, settings: Settings) -> None:
    message = MESSAGE_TEMPLATE.format(name=contact.name)

    if settings.dry_run:
        logging.info("[DRY_RUN] Enviaria para %s: %s", contact.phone, message)
        return

    url = (
        "https://api.z-api.io/instances/"
        f"{settings.zapi_instance_id}/token/{settings.zapi_token}/send-text"
    )
    payload = {"phone": contact.phone, "message": message}
    headers = {"Client-Token": settings.zapi_client_token}

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    logging.info("Mensagem enviada para %s (%s)", contact.name, contact.phone)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        settings = load_settings()
        supabase = create_client(settings.supabase_url, settings.supabase_key)
        contacts = fetch_contacts(supabase, settings)

        if not contacts:
            logging.warning("Nenhum contato válido encontrado no Supabase.")
            return 0

        for contact in contacts:
            try:
                send_message(contact, settings)
            except requests.RequestException as error:
                logging.error(
                    "Erro ao enviar mensagem para %s (%s): %s",
                    contact.name,
                    contact.phone,
                    error,
                )

        return 0
    except Exception as error:
        logging.exception("Execução interrompida: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
