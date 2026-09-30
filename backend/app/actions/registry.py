"""Each action has a strict schema, permission, effect and service handler."""

from dataclasses import dataclass
from typing import Callable, Literal
from uuid import UUID
from pydantic import BaseModel, create_model
from ..services import ledger, websites, data
from .base import Arguments, IdArguments, MonthArguments


@dataclass(frozen=True)
class Action:
    name: str
    schema: type[BaseModel]
    scope: str
    effect: str
    entity_type: str
    handler: Callable


REGISTRY: dict[str, Action] = {}


def register(
    name, module, function, schema, effect, entity_type, *, id_field=None, payload=False
):
    domain = "websites" if name.startswith("website.") else name.split(".")[0]

    def handler(db, owner, arguments):
        values = arguments.model_dump(mode="json", exclude_unset=True)
        kwargs = {"db": db, "user": owner}
        if id_field:
            kwargs["id"] = str(values.pop(id_field))
        if payload:
            # Validate with the exact same business input model as ordinary REST.
            kwargs["payload"] = schema.__bases__[0].model_validate(values)
        else:
            kwargs.update(values)
        return getattr(module, function)(**kwargs)

    REGISTRY[name] = Action(
        name, schema, f"{domain}:{effect}", effect, entity_type, handler
    )


def business_schema(name, base, **fields):
    # Reuse every business validator and field constraint; reject extra ownership.
    return create_model(name, __base__=(base, Arguments), **fields)


class WebsiteList(Arguments):
    categoryId: UUID | None = None
    search: str | None = None
    favorite: bool | None = None
    sort: Literal["order", "name", "createdAt", "updatedAt", "recent"] = "order"


class RecordsList(Arguments):
    collectionId: UUID


register(
    "ledger.categories.list",
    ledger,
    "list_categories",
    Arguments,
    "read",
    "ledger.category",
)
register(
    "ledger.transactions.list",
    ledger,
    "list_transactions",
    MonthArguments,
    "read",
    "ledger.transaction",
)
register(
    "ledger.summary.get",
    ledger,
    "summary",
    MonthArguments,
    "read",
    "ledger.transaction",
)
register(
    "website.categories.list",
    websites,
    "list_categories",
    Arguments,
    "read",
    "website.category",
)
register("website.list", websites, "list_websites", WebsiteList, "read", "website")
register(
    "website.get",
    websites,
    "get_website",
    IdArguments,
    "read",
    "website",
    id_field="id",
)
register(
    "website.visit",
    websites,
    "visit_website",
    IdArguments,
    "write",
    "website",
    id_field="id",
)
register(
    "data.collections.list",
    data,
    "list_collections",
    Arguments,
    "read",
    "data.collection",
)
register(
    "data.collection.get",
    data,
    "get_collection",
    IdArguments,
    "read",
    "data.collection",
    id_field="id",
)
register(
    "data.records.list",
    data,
    "list_records",
    RecordsList,
    "read",
    "data.record",
    id_field="collectionId",
)
register(
    "data.record.get",
    data,
    "get_record",
    IdArguments,
    "read",
    "data.record",
    id_field="id",
)

for (
    prefix,
    module,
    entity_type,
    create_fn,
    update_fn,
    delete_fn,
    input_model,
    patch_model,
) in [
    (
        "ledger.category",
        ledger,
        "ledger.category",
        "create_category",
        "patch_category",
        "delete_category",
        ledger.CategoryInput,
        ledger.CategoryPatch,
    ),
    (
        "ledger.transaction",
        ledger,
        "ledger.transaction",
        "create_transaction",
        "patch_transaction",
        "delete_transaction",
        ledger.TransactionInput,
        ledger.TransactionPatch,
    ),
    (
        "website.category",
        websites,
        "website.category",
        "create_category",
        "update_category",
        "delete_category",
        websites.CategoryInput,
        websites.CategoryPatch,
    ),
    (
        "website",
        websites,
        "website",
        "create_website",
        "update_website",
        "delete_website",
        websites.WebsiteInput,
        websites.WebsitePatch,
    ),
    (
        "data.collection",
        data,
        "data.collection",
        "create_collection",
        "patch_collection",
        "delete_collection",
        data.CollectionInput,
        data.CollectionPatch,
    ),
    (
        "data.record",
        data,
        "data.record",
        "create_record",
        "patch_record",
        "delete_record",
        data.RecordInput,
        data.RecordPatch,
    ),
]:
    extra = {"collectionId": (UUID, ...)} if prefix == "data.record" else {}
    register(
        prefix + ".create",
        module,
        create_fn,
        business_schema(prefix.replace(".", "_") + "Create", input_model, **extra),
        "write",
        entity_type,
        id_field="collectionId" if extra else None,
        payload=True,
    )
    register(
        prefix + ".update",
        module,
        update_fn,
        business_schema(
            prefix.replace(".", "_") + "Update", patch_model, id=(UUID, ...)
        ),
        "write",
        entity_type,
        id_field="id",
        payload=True,
    )
    register(
        prefix + ".delete",
        module,
        delete_fn,
        IdArguments,
        "delete",
        entity_type,
        id_field="id",
    )
