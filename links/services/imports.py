import csv
import io
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from links.forms import LinkForm
from links.models import Campaign, ImportBatch, Tag
from links.services.links import save_link

HEADERS = ["title", "destination", "alias", "campaign", "tags", "max_clicks", "expires_at"]


def read_csv(upload):
    if upload.size > 262144:
        raise ValidationError("CSV must be at most 256 KB.")
    try:
        text = upload.read(262145).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames or []
        if len(set(headers)) != len(headers) or "destination" not in headers or set(headers) - set(HEADERS):
            raise ValidationError(
                "Use the sample headers. destination is required; duplicate or unknown columns are not allowed."
            )
        rows = []
        for number, row in enumerate(reader, start=2):
            if number > 201:
                raise ValidationError("CSV is limited to 200 data rows.")
            if None in row or any(value is None for value in row.values()):
                raise ValidationError(f"Row {number} does not match the header columns.")
            rows.append({k: v.strip() for k, v in row.items()})
        if not rows:
            raise ValidationError("CSV has no data rows.")
        return rows
    except (UnicodeDecodeError, csv.Error):
        raise ValidationError("Could not read the file. Use a UTF-8 CSV with valid quoting.") from None


def row_form(workspace, row):
    data = {
        "title": row.get("title") or row.get("destination", "")[:120],
        "destination": row.get("destination", ""),
        "alias": row.get("alias", ""),
        "max_clicks": row.get("max_clicks", ""),
        "expires_at": row.get("expires_at", ""),
        "status": "active",
        "tags": [],
    }
    errors = []
    if row.get("campaign"):
        campaign = Campaign.objects.filter(workspace=workspace, name=row["campaign"]).first()
        if campaign:
            data["campaign"] = campaign.pk
        else:
            errors.append("Campaign does not exist in this workspace.")
    for name in filter(None, (x.strip() for x in row.get("tags", "").split(";"))):
        tag = Tag.objects.filter(workspace=workspace, name=name).first()
        if tag:
            data["tags"].append(tag.pk)
        else:
            errors.append(f"Unknown tag: {name}.")
    form = LinkForm(data, workspace=workspace)
    form.is_valid()
    for error in errors:
        form.add_error(None, error)
    return form


def preview_rows(workspace, rows):
    results = []
    aliases = set()
    for number, row in enumerate(rows, start=2):
        form = row_form(workspace, row)
        errors = [str(message) for messages in form.errors.values() for message in messages]
        alias = row.get("alias")
        if alias and alias in aliases:
            errors.append("Duplicate alias in this CSV.")
        if alias:
            aliases.add(alias)
        results.append(
            {
                "row": number,
                "title": row.get("title", ""),
                "destination": row.get("destination", ""),
                "errors": errors,
                "state": "invalid" if errors else "ready",
            }
        )
    return results


def confirm_batch(actor, batch_id):
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id, workspace__owner=actor)
        if batch.completed_at:
            return batch
        if batch.created_at < timezone.now() - timedelta(minutes=30):
            raise ValidationError("This preview expired. Upload the file again.")
        results = []
        for row, preview in zip(batch.rows, batch.results, strict=True):
            result = dict(preview)
            if result["errors"]:
                results.append(result)
                continue
            form = row_form(batch.workspace, row)
            if not form.is_valid():
                result.update(
                    state="invalid", errors=[str(m) for messages in form.errors.values() for m in messages]
                )
            else:
                try:
                    with transaction.atomic():
                        link = save_link(actor, batch.workspace, form.cleaned_data)
                    result.update(state="created", alias=link.alias, short_url=link.short_url)
                except ValidationError as error:
                    result.update(state="invalid", errors=error.messages)
            results.append(result)
        batch.results = results
        batch.completed_at = timezone.now()
        batch.save(update_fields=["results", "completed_at"])
        return batch
