import dataclasses
import functools
import itertools
import json
import pathlib
import sqlite3
import tempfile
import zipfile


@dataclasses.dataclass(frozen=True)
class Model:
    name: str
    field_names: list[str]


@dataclasses.dataclass(frozen=True)
class Note:
    model: Model
    field_contents: list[str]
    tags: set[str]

    @functools.cached_property
    def fields(self) -> dict[str, str]:
        return dict(itertools.zip_longest(self.model.field_names, self.field_contents, fillvalue=""))


@dataclasses.dataclass(frozen=True)
class Collection:
    models: list[Model]
    notes: list[Note]


def read_package(path: pathlib.Path) -> Collection:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        with zipfile.ZipFile(path) as zf:
            zf.extract("collection.anki2", path=tmpdir)

        with sqlite3.connect(tmpdir / "collection.anki2") as conn:
            models_json, = conn.execute("SELECT models FROM col").fetchone()
            notes_rows = conn.execute("SELECT mid,flds,tags FROM notes").fetchall()

    models = {}
    for mid, model in json.loads(models_json).items():
        name = model["name"]
        field_names = [fld["name"] for fld in model["flds"]]
        models[int(mid)] = Model(name=name, field_names=field_names)

    notes = []
    for mid, flds, tags in notes_rows:
        model = models[mid]
        fields = flds.split("\x1f")
        tags = set(tags.strip().split())
        note = Note(model=model, field_contents=fields, tags=tags)
        notes.append(note)
    
    return Collection(models, notes)